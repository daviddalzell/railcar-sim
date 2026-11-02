<!-- SPDX-FileCopyrightText: 2026 David Dalzell -->
<!-- SPDX-License-Identifier: MIT -->

# 800-Car Performance: Evaluation & Fix Plan

**Status:** Planned, not yet implemented. Phases are ordered by impact/effort.

## Context

A user wants to upload ~800 cars. The app is tuned for demo layouts of ~15 cars, so this is ~50x larger. A review of the car data path confirmed real performance cliffs — not hypothetical. At 800 cars the roster load, the Operations tab, and auto-assign become slow or unusable. Phase 1 alone makes 800 cars usable.

## Evaluation — confirmed bottlenecks

Root cause on the backend: every relationship in `models.py` uses the default `lazy="select"`, and the car endpoints map `car_to_dict` over every car with no eager loading.

| Area | Scaling | Cost at 800 cars |
|---|---|---|
| `GET /api/cars` (`routers/cars.py:63`) | N+1 queries | ~1,600–4,000 SQLite queries; ~0.5–1 MB JSON; refetched after every edit |
| Roster render (`renderCarGrid`, `static/app.js:499`) | linear, bad constants | ~800 DOM cards; ~800 eager image requests (no `loading="lazy"` at `app.js:452`); 800 individual click listeners; full rebuild after every single-car edit |
| `GET /api/operations` (`routers/operations.py:57`) | N+1 **+1/car** | `car_to_dict` N+1 plus a MovementLog query per car ≈ 2,400–4,000+ queries; 800-row render + 800 thumbnails |
| `auto-assign-waybills` (`routers/automation.py:370`) | **O(cars × waybills)** | `random.shuffle(unassigned)` per car + per-slot scans + 800 `db.refresh` + full N+1 payload |
| Import commit (`routers/export_import.py:289`) | linear | per-row ORM `db.add` INSERTs; full existing-car dup scan; full `rows` array round-trips client↔server twice |

`generate-waybills` scales with layout size, not car count — unaffected. Dispatcher build-plan is scoped per-area — fine unless one track holds hundreds of cars.

## Recommended solutions (phased)

### Phase 1 — makes 800 cars usable (small, surgical, low risk)

1. **Lazy-load car images.** Add `loading="lazy"` to the `<img>` tags in `carCardHTML` (`app.js:452`, `:454`) and the Operations thumbnail render (~`app.js:1479`). Removes the ~800-request image storm. The photo-library grid already does this at `app.js:293`.
2. **Kill the N+1 on `/api/cars`** (`routers/cars.py:65`). Add eager loading: `selectinload(Car.waybills)` with nested `origin`/`destination`/`industry`, plus `selectinload(Car.current_location)`. Collapses thousands of queries into a handful. Confirm relationship names in `models.py` first.
3. **Same eager loading for `/api/operations`** (`routers/operations.py:57`) and batch the per-car MovementLog lookup into one grouped query.
4. **Event delegation in `renderCarGrid`** (`app.js:526`). One delegated listener on `#car-grid` / `#power-pool-list` reading `data-id`, instead of 800 listeners.
5. **Bulk insert on import.** In `commit_car_import` (`export_import.py:306`) and `import_cars` (`:271`), replace the per-row `db.add` loop with `db.bulk_insert_mappings(Car, mappings)`.

### Phase 2 — handles edits & auto-assign at scale

6. **Fix the auto-assign algorithm** (`automation.py:370`, `auto_assign_one_car:130`). Shuffle the unassigned pool once (not per car); index unassigned waybills by match key for O(1) lookup; drop the per-car `db.refresh`. Turns O(cars × waybills) into ~O(cars + waybills).
7. **Stop full-roster refetch on single-car edits.** Several flows call `loadRoster()` after editing one car (`app.js:880`, `:967`, `:1055`, `:3269`). Patch the single car in the `cars` state array and re-render only its card. This is a win at any roster size.

### Phase 3 — scale to thousands (optional, larger)

8. **Roster pagination or windowed rendering** plus a search/filter box, so the DOM holds a bounded number of cards. Pair with server-side pagination/search on `/api/cars`. **Do not apply to small rosters** — it adds complexity and only benefits large ones.

## Impact on normal rosters (15–30 cars)

These changes target large rosters. At 15–30 cars the app is already fast, so users there will not perceive a speedup — but nothing regresses. Phases 1–2 are neutral-to-positive at small scale; #7 (snappier single-car edits) is a win at any size. Phase 3 is gated on roster size.

## Key files

`routers/cars.py`, `routers/operations.py`, `routers/automation.py`, `routers/export_import.py` (backend); `static/app.js` (`carCardHTML`, `renderCarGrid`, Operations render, single-car-edit flows); `models.py` (read-only, to confirm relationship names). `converters.py` needs no change — eager loading is applied at the query options.

## Verification

1. **Seed 800 cars** in local SQLite (ORM factories or a generated `/api/import/cars/commit` payload).
2. **Backend, before/after:** count SQL queries per `GET /api/cars` and `/api/operations` with a SQLAlchemy `before_cursor_execute` counter; confirm the count drops from thousands to a small constant.
3. **Add a perf-guard test** (`tests/test_car_scaling.py`): seed N cars, assert `GET /api/cars` issues a bounded number of queries independent of N — same spirit as `tests/test_dialogs.py`, catches future N+1 regressions.
4. **Browser** (`AUTH_DISABLED=1 uvicorn main:app`): load 800 cars; confirm images load lazily on scroll, the grid renders quickly, and editing one car does not refetch all cars.
5. **Auto-assign:** run with 800 cars and a large unassigned pool; confirm it completes quickly with a bounded query count.

## Branch & workflow

Branch `feature/car-scaling-phase1` off `main` for Phase 1; open a PR (pre-commit runs the suite). Phase 2 and Phase 3 as follow-on branches so each ships and is verified independently.
