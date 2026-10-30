# Waypoint — Claude Code Guide

## Project overview

Waypoint is a multi-tenant model railway operations web app. Operators build car rosters, assign waybills, run operating sessions, and dispatch trains. Each tenant (club or individual) gets an isolated Postgres schema. A public demo tenant lives at `demo.waypoint-ops.com`.

**Stack:** FastAPI · SQLAlchemy · Alembic · Supabase (Postgres + Auth) · Fly.io · Vanilla JS frontend (single `static/app.js`) · Jinja2 templates

---

## Workflow

### Branching
- **Always create a branch before any feature work.** Never commit features directly to `main`.
- Branch naming: `feature/<short-description>` (e.g. `feature/layout-rename-frontend`)
- Bug fixes and small copy/CSS changes can go directly to `main`.

### Pull requests
- Open PRs with `gh pr create`
- Target branch is always `main`
- PRs require passing tests (pre-commit hook runs pytest automatically)

### Deployment
- Fly.io app: `waypoint-app`
- **Auto-deploys at 4am Central time** on merge to `main`
- Manual deploy: `fly deploy -a waypoint-app --strategy immediate`
- Release command runs before new VMs start: `python -m admin.migrate_all_tenants`
- If the release command fails, Fly aborts and keeps the previous version running

---

## Database & migrations

### Architecture
- Multi-tenant: each tenant has a dedicated Postgres schema (`t_{slug}`)
- `public` schema holds shared tables: `tenants`, `tenant_members`, `access_keys`, `demo_leads`, `page_views`
- Tenant schemas hold all layout data: `cars`, `locations`, `tracks`, `industries`, `waybills`, etc.
- Alembic manages all Postgres schema changes. SQLite (local dev) uses `init_db()` inline migrations.

### Critical migration rules

**1. Never call `create_all()` on Postgres.**
`init_db()` in `database.py` calls `Base.metadata.create_all()` only for SQLite. The `if not _is_sqlite: return` guard must come *before* `create_all()`. Alembic owns the Postgres schema.

**2. Public-schema migrations must use `IF NOT EXISTS` / `IF EXISTS`.**
`admin/migrate_all_tenants.py` runs `alembic upgrade head` once per tenant schema. Any migration that touches a `public.*` table will be attempted once per tenant and will crash on DuplicateColumn/DuplicateTable on the second run. Always use raw SQL:
```python
op.execute(sa.text("ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS col_name TYPE"))
op.execute(sa.text("CREATE TABLE IF NOT EXISTS public.my_table (...)"))
```

**3. Table rename ordering matters.**
When renaming two tables where the new name of one conflicts with the current name of the other, rename the lower-level table first. Example: to rename `switching_areas→locations` and `locations→tracks`, rename `locations→tracks` first to free the name.

### Running migrations locally
```bash
alembic upgrade head                          # public schema
alembic -x schema=t_myslug upgrade head      # specific tenant schema
python -m admin.migrate_all_tenants           # all tenants (as Fly does)
```

---

## Testing

```bash
pytest tests/ -q
```

All tests run automatically before each commit (pre-commit hook). Do not use `--no-verify`.

Test helpers live in `tests/conftest.py`: `make_car`, `make_location` (creates a `Track`), `make_industry`.

---

## Key files

| File | Purpose |
|---|---|
| `models.py` | SQLAlchemy models for all tenant tables |
| `schemas.py` | Pydantic request/response schemas |
| `converters.py` | Model → dict helpers used by all routers |
| `routers/locations.py` | Track + Location CRUD (`/api/tracks`, `/api/locations`, `/api/switching-areas`) |
| `routers/dispatcher.py` | Consist building and dispatch plans |
| `routers/session.py` | Operating session state machine |
| `routers/automation.py` | Waybill generation and auto-assignment |
| `middleware/tenant.py` | Resolves tenant from subdomain; sets `request.state.tenant` |
| `auth.py` | Supabase JWT validation; `get_current_user` dependency |
| `admin/migrate_all_tenants.py` | Runs Alembic across every tenant schema (Fly release command) |
| `admin/seed_demo.py` | Seeds the demo tenant with sample data |
| `static/app.js` | Entire frontend (~4000 lines, vanilla JS) |
| `templates/index.html` | Main app shell (Jinja2) |

---

## Domain model

```
Location          (town, yard complex, or staging area)
  └── Track       (individual siding or track — has location_type: yard/industry/staging/storage)
        └── Industry  (customer on an industry-type track)
                        └── Waybill  (car movement instruction)
Car               (rolling stock — has current_location_id pointing to a Track)
DispatchPlan      (consist built by the virtual dispatcher)
```

**Backward-compat aliases** kept for the old frontend (remove in PR 2):
- `GET/POST /api/locations` → Track CRUD (was the old location endpoint)
- `GET/POST /api/switching-areas` → Location CRUD (was the old switching area endpoint)

---

## Conventions

- **No comments** unless the WHY is non-obvious
- **No `create_all()` on Postgres** — see migration rules above
- Response dicts keep both old and new key names during transition (e.g. `switching_area_id` + `location_id`) — remove old keys in PR 2
- The demo tenant bypasses Supabase auth; all other tenants validate JWTs
- Tenant cache (`middleware/tenant.py`) is in-memory; call `invalidate_tenant_cache(slug)` after updating a tenant row
- `fly ssh console -a waypoint-app` for production debugging; use `fly sftp shell` to upload scripts first
