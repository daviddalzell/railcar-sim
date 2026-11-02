# Waypoint — Claude Code Guide

## Project overview

Waypoint is a multi-tenant model railway operations web app. Operators build car rosters, assign waybills, run operating sessions, and dispatch trains. Each tenant (club or individual) gets an isolated Postgres schema. A public demo tenant lives at `demo.waypoint-ops.com`.

**Stack:** FastAPI · SQLAlchemy · Alembic · Supabase (Postgres + Auth) · Fly.io · Vanilla JS frontend (single `static/app.js`) · Jinja2 templates

---
### Standard instruction: use Simplified Technical English

Before you write any direct response to me, ensure it is written in ASD-STE100 Simplified Technical English.
• Use active voice and simple tenses.
• Keep sentences short and direct (maximum 20–25 words per sentence).
• State one clear idea or instruction per sentence.
• Do not invent, infer, or use unmapped acronyms, metaphors, or marketing fluff.
• Use the exact technical and domain nouns that already exist in the codebase or context.

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

## Local development

```bash
# Install deps
pip install -r requirements.txt

# Run with SQLite (no Supabase needed)
AUTH_DISABLED=1 uvicorn main:app --reload

# Run against production Postgres (copy from Fly secrets)
cp .env.example .env   # fill in DATABASE_URL + SUPABASE_* vars
uvicorn main:app --reload
```

SQLite mode uses a local `railcar.db` file. `init_db()` creates the schema automatically — no Alembic needed. `AUTH_DISABLED=1` skips Supabase auth and returns a synthetic admin user for every request.

---

## Environment variables

### Required in production (set as Fly secrets)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Supabase Postgres connection string |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase service role key (admin — keep secret) |
| `SUPABASE_ANON_KEY` | Supabase anon key (used client-side) |

### Optional / feature flags

| Variable | Purpose |
|---|---|
| `AUTH_DISABLED` | Set to any value to skip auth (local dev only) |
| `DEFAULT_TENANT_SLUG` | Fallback tenant when subdomain doesn't match (e.g. during DNS setup) |
| `ADMIN_PASSWORD` | Password for `/admin` routes |
| `SYNC_SECRET` | Shared secret for Patreon webhook validation |
| `PATREON_ACCESS_TOKEN` | Patreon API token for member sync |
| `PATREON_CAMPAIGN_ID` | Patreon campaign to sync from |
| `PATREON_WEBHOOK_SECRET` | Patreon webhook signature validation |
| `APP_URL` | Base URL (e.g. `https://waypoint-ops.com`) — used in emails |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `SMTP_FROM` | Welcome email SMTP config |
| `DEMO_TEMPLATE_EMAIL` | Email of the Supabase user whose layout seeds the demo |
| `VISION_PROVIDER` | AI vision provider: `gemini` (default), `openai`, or `ollama` |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | Gemini vision config |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | Anthropic (Claude) config |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | OpenAI config |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` / `OLLAMA_NUM_CTX` / `OLLAMA_MAX_IMAGE_PX` | Local Ollama config |
| `AI_MAX_RETRIES` / `AI_RETRY_BASE_DELAY` | AI retry tuning |
| `LOG_FORMAT` | Set to `json` on Fly for structured logs |

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

## Admin scripts (`admin/`)

| Script | Usage | Purpose |
|---|---|---|
| `migrate_all_tenants.py` | Fly release command | Runs `alembic upgrade head` for public schema + every tenant schema |
| `provision_tenant.py` | `python -m admin.provision_tenant --slug=x --name="X" --admin-email=x@x.com` | Creates Postgres schema, seeds defaults, creates Supabase auth user, sends welcome email |
| `seed_demo.py` | `python -m admin.seed_demo` | Wipes and reseeds the demo tenant with sample layout data (runs nightly in production) |
| `reset_demo.py` | `python -m admin.reset_demo` | Alias for seed_demo used by the nightly cron |
| `reset_tenant.py` | `python -m admin.reset_tenant --slug=x` | Wipes all layout data for a tenant (keeps the tenant row and auth users) |
| `clone_demo.py` | `python -m admin.clone_demo --slug=x` | Copies demo layout data into a tenant's schema |
| `sync_patreon.py` | `python -m admin.sync_patreon` | Syncs Patreon members → tenant subscription status |

---

## Tenant management

### Provisioning a new tenant
```bash
python -m admin.provision_tenant \
  --slug club-springfield \
  --name "Springfield Model Railroad Club" \
  --admin-email admin@springfield.com
```
This creates schema `t_club_springfield`, seeds car types + commodity map, inserts the `public.tenants` row, and sends a Supabase invite email.

### Diagnosing a tenant with missing data
Upload a diagnostic script via `fly sftp shell`, then run it:
```bash
fly sftp shell -a waypoint-app <<'EOF'
put /path/to/diagnose.py /app/diagnose.py
EOF
fly ssh console -a waypoint-app -C "python /app/diagnose.py"
```
Check: tenant row exists in `public.tenants`, schema exists, table counts > 0, `subscription_status = 'active'`.

### Auth / JWT
- Tenant is resolved from the **subdomain** (`host` header), not from the JWT
- JWT metadata fields that matter: `role` (`admin` or `operator`), `tenant_slug`
- Default role if not set: `operator` (read-only for most resources)
- Demo tenant bypasses Supabase auth entirely — any request to `demo.waypoint-ops.com` gets a synthetic admin user
- Revoked users are tracked in `public.tenant_members` (`is_active = false`)
- Tenant context is cached in-memory; call `invalidate_tenant_cache(slug)` after updating a tenant row

---

## Frontend (`static/app.js`)

Single file, ~4000 lines, vanilla JS. Major sections in order:

| Line | Section |
|---|---|
| 6 | **State** — module-level arrays: `cars`, `locations` (Locations), `tracks`, `industries`, `waybills`, `switchingAreas` |
| 143 | **Helpers** — `api()`, `showToast()`, `withLoading()`, `track()` (GA events) |
| 242 | **Photo library** — `openPhotoLibrary()`, `refreshLibraryGrid()` |
| 397 | **Tab navigation** — tab switching, URL hash handling |
| 423 | **Roster** — `loadRoster()`, `renderCarGrid()`, `carCardHTML()` |
| 624 | **Add car via photo** — `processPhotoFile()`, `runStylize()`, `applyAnalysis()` |
| 891 | **Car detail dialog** — `openCarDetail()` |
| 1236 | **Waybill pool** — `loadWaybillPool()`, `renderWaybillPool()`, `openWaybillEditDialog()` |
| 1396 | **Operations view** — `loadOperations()`, `renderPlanPreview()` |
| 1591 | **Operating session** — `renderActiveSession()`, `detectSpottingConflicts()`, `handleEndSession()` |
| 2047 | **Layout setup** — `loadLayout()`, `renderLocationTree()`, `renderIndustryList()`, `renderCarTypeList()` |
| 2864 | **Export / Import** — backup download and ZIP restore |
| 3107 | **Location tree helpers** — `buildTrackOptgroups()`, `openCascadeDeleteDialog()`, inline rename |
| 3218 | **Layout status strip** — `renderLayoutStatus()` |
| 3284 | **Dispatcher** — `loadDispatcherPanel()`, `renderConsistCard()`, `wireConsistCard()` |
| 3757 | **Settings tab** — `loadSettings()`, `loadMembers()` |
| 3966 | **Bootstrap** — `init()` entry point; loads all tabs, wires event listeners, opens dialogs |
| 4019 | **AI notice / Demo welcome** — dialog button handlers |

Key patterns:
- `api(method, path, body)` — all fetch calls go through this; throws on non-2xx
- `showToast(message, type, duration)` — user feedback
- `withLoading(btn, label, fn)` — disables a button, shows spinner, re-enables after `fn` resolves
- `track(eventName, params)` — Google Analytics event helper

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

**Endpoints** (PR 2 removed the old backward-compat aliases):
- `GET/POST/PUT/DELETE /api/tracks` → Track CRUD
- `GET/POST/PUT/DELETE /api/locations` → Location (group) CRUD

---

## Layout rename (PR 2 — complete)

The Location/Track rename is applied on both backend and frontend:
- `renderLocationTree()` replaces the old flat Location and Switching Area lists — a 3-level tree (Location → Track → Industry) with localStorage collapse state and click-to-edit inline rename.
- API: `/api/tracks` is Track CRUD; `/api/locations` is Location (group) CRUD. The old `/api/switching-areas` alias is removed.
- Backward-compat response keys (`switching_area_id`, `switching_areas`) are removed.
- All track selects group tracks by Location via `<optgroup>` (`buildTrackOptgroups()`).
- All layout deletes use a cascade-warning dialog (`openCascadeDeleteDialog()`).
- `app.js` is cache-busted with the git SHA (`asset_version` in `main.py`).
- Touch layout: accordion tree plus bottom-sheet forms at a single breakpoint (≤1024px). A desktop split is a future enhancement.

---

## Conventions

### Python naming
- Leading underscore (`_fn`) only for functions that are **private to a single module** (e.g. `_run_build_algorithm` in `routers/dispatcher.py`)
- Shared helpers in `converters.py`, `schemas.py` etc. are public exports — no underscore
- No leading underscores on module-level variables or constants

### General
- **No comments** unless the WHY is non-obvious
- **No `create_all()` on Postgres** — see migration rules above
- Response dicts use the current key names only (`location_id`, `tracks`); the old `switching_area_*` keys were removed in PR 2
- The demo tenant bypasses Supabase auth; all other tenants validate JWTs
- Tenant cache (`middleware/tenant.py`) is in-memory; call `invalidate_tenant_cache(slug)` after updating a tenant row
- `fly ssh console -a waypoint-app` for production debugging; use `fly sftp shell` to upload scripts first
