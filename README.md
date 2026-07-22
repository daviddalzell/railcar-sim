# Waypoint — Model Railroad Operations

A web app for managing a model railroad car roster, waybills, and operations. Optionally uses an AI vision model to identify car details from a photo. Supports multi-tenant cloud deployment via Fly.io + Supabase.

---

## Requirements

- Python 3.11 or later
- (Optional) An API key for your chosen AI vision provider, or a running [Ollama](https://ollama.com) instance for local open-source models

---

## Local development setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd railcar-sim
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Activate the pre-commit hook

```bash
git config core.hooksPath scripts/hooks
```

This runs the test suite before every commit and blocks the commit if any test fails.

### 5. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in the values for your chosen vision provider (see [Vision Providers](#vision-providers) below). If you skip this step the app still works — fill in car details manually after uploading a photo.

### 6. Run the app

```bash
.venv/bin/python3 -m uvicorn main:app --reload
```

Open [http://localhost:8000](http://localhost:8000). The `--reload` flag restarts the server on source changes.

Locally the app uses SQLite (`railcar.db` in the project root, created automatically). No database setup required.

---

## Cloud deployment (Fly.io + Supabase)

### Prerequisites

- [flyctl](https://fly.io/docs/hands-on/install-flyctl/) installed and authenticated
- A [Supabase](https://supabase.com) project (free tier is fine)
- A [Patreon](https://www.patreon.com) creator account (for subscription-based tenant provisioning)

### Required Fly secrets

Set these with `flyctl secrets set KEY=value --app waypoint-app`:

| Secret | Where to get it |
|---|---|
| `DATABASE_URL` | Supabase → Project Settings → Database → Connection string (Transaction pooler, port 6543) |
| `SUPABASE_URL` | Supabase → Project Settings → API → Project URL |
| `SUPABASE_KEY` | Supabase → Project Settings → API → `service_role` secret key |
| `SUPABASE_ANON_KEY` | Supabase → Project Settings → API → `anon` public key |
| `PATREON_WEBHOOK_SECRET` | Patreon creator portal → My integrations → Webhooks → secret |
| `VISION_PROVIDER` | One of: `gemini`, `anthropic`, `openai`, `ollama` |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com) → API keys |
| `DEFAULT_TENANT_SLUG` | Slug of the fallback tenant when no subdomain is present (e.g. `demo`) |
| `ADMIN_PASSWORD` | Password for the admin dashboard at `/admin/dashboard` |
| `SMTP_USER` | Gmail address for outbound email (invites, welcome emails, renewal reminders) |
| `SMTP_PASS` | Gmail app password (16 chars, spaces stripped automatically) |

### Deploy

```bash
flyctl deploy --app waypoint-app
```

On every deploy the startup command runs `python -m admin.migrate_all_tenants`, which applies `alembic upgrade head` to the `public` schema and to every `t_{slug}` tenant schema before uvicorn starts.

### Custom domain (wildcard subdomain)

Each tenant is served at `{slug}.yourdomain.com`. Once your DNS is configured:

```bash
flyctl certs add "*.yourdomain.com" --app waypoint-app
```

Point a wildcard `CNAME` (`*.yourdomain.com`) at your Fly app hostname.

---

## Multi-tenant architecture

Each Supabase/Postgres tenant gets its own schema (`t_{slug}`) that is fully isolated from other tenants. The `public` schema holds the `tenants` registry and is used by the built-in demo tenant.

Tenant resolution: the app reads the subdomain from the `Host` header and looks up the matching row in `public.tenants`. The `DEFAULT_TENANT_SLUG` secret provides a fallback for non-subdomain access (e.g. direct Fly hostname).

### Provisioning a tenant manually

```bash
python -m admin.provision_tenant \
  --slug myclub \
  --name "My Club" \
  --admin-email admin@example.com
```

This creates the `t_myclub` schema, all tables, and sends a Supabase Auth invite to the admin email.

### Access key provisioning (direct / non-Patreon)

Use this to provision tenants for users who pay via Venmo or any other out-of-band method, without requiring a Patreon subscription.

**Required Fly secret:**

```bash
flyctl secrets set ADMIN_PASSWORD=yourpassword --app waypoint-app
```

**Workflow:**

1. Visit `https://waypoint-ops.com/admin/dashboard` and sign in with `ADMIN_PASSWORD`.
2. Go to the **Keys** tab → fill in slug, layout name, admin email, duration (days), and an optional private note (e.g. `"Venmo @alice $25 2026-07-11"`).
3. Click **Generate key** → copy the `RAIL-XXXX-XXXX` code → send it to the user by email.
4. The user visits `https://waypoint-ops.com`, enters the code, and clicks **Activate** — the tenant is provisioned and a welcome email is sent automatically.

**Managing leases from the dashboard:**

- **Tenants tab** — extend a lease (add days), suspend, reactivate, or delete any tenant.
- **Reminders tab** — send renewal reminder emails to all tenants expiring within 30 days. Run this manually, or automate with a cron job:

```bash
# Example: run daily at 9 AM (requires X-Sync-Secret)
0 9 * * * curl -s -X POST https://waypoint-ops.com/admin/send-renewal-reminders \
  -H "Cookie: admin_session=<token>"
```

Renewals are always manual — the user contacts David, pays via Venmo, and David clicks **Extend** in the dashboard.

### Patreon webhook (automatic provisioning)

1. In the Patreon creator portal → **My integrations → Webhooks**, create a webhook pointing to `https://your-fly-hostname/webhooks/patreon` and subscribe to `members:pledge:create`, `members:pledge:delete`, and `members:pledge:update`.
2. Copy the webhook secret into `PATREON_WEBHOOK_SECRET`.

When a new patron pledges, a tenant is automatically provisioned and the patron receives a Supabase magic-link invite. When a patron cancels, the tenant enters a 30-day grace period before suspension.

### Per-tenant AI settings

Tenant admins can configure their own vision provider and API keys in the **Settings** tab. These override the server-level environment variables for that tenant only.

---

## Running migrations across all tenants

The Dockerfile CMD does this automatically on every deploy. To run it manually (e.g. after adding a new migration in development):

```bash
python -m admin.migrate_all_tenants
```

To add a new migration:

```bash
alembic revision --autogenerate -m "describe the change"
```

Then commit the generated file. The next deploy will apply it to all tenant schemas.

---

## Vision Providers

The app can analyse a photo of a model railroad car and pre-fill the car type, colour, number, and reporting marks. Set `VISION_PROVIDER` in your `.env` file (local) or as a Fly secret (cloud).

### Gemini (cloud default)

```env
VISION_PROVIDER=gemini
GEMINI_API_KEY=your-key-here
# GEMINI_MODEL=gemini-2.0-flash-lite   # optional
```

Get a key at [Google AI Studio](https://aistudio.google.com) → API keys.

### Anthropic

Uses Claude's vision API.

```env
VISION_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key-here
```

Get a key at [console.anthropic.com](https://console.anthropic.com) → API Keys.

### OpenAI

Uses GPT-4o vision.

```env
VISION_PROVIDER=openai
OPENAI_API_KEY=your-key-here
# OPENAI_MODEL=gpt-4o   # optional, gpt-4o is the default
```

### Ollama (local / open-source)

Runs a vision model locally — no API key required. Install the [Ollama macOS app](https://ollama.com/download/mac) and set:

```env
VISION_PROVIDER=ollama
# OLLAMA_MODEL=llava                          # optional, llava is the default
# OLLAMA_BASE_URL=http://localhost:11434/v1   # optional, this is the default
```

When the app starts it will automatically launch the Ollama daemon if it isn't already running, and pull the configured model if it hasn't been downloaded yet. The first pull may take several minutes.

### No vision provider

If no provider is configured (or the API key is missing), the app still works — fill in car details manually after uploading a photo.

---

## Project structure

```
railcar-sim/
├── main.py              # FastAPI app entry point and router registration
├── schemas.py           # Pydantic request/response models
├── converters.py        # Shared model-to-dict helpers
├── models.py            # SQLAlchemy database models (incl. Tenant)
├── database.py          # DB connection; schema-switching get_db()
├── vision.py            # AI vision provider implementations
├── auth.py              # Supabase JWT verification
├── storage.py           # Supabase Storage / local uploads helper
├── routers/             # API route handlers (one file per domain)
│   ├── cars.py
│   ├── waybills.py
│   ├── locations.py
│   ├── industries.py
│   ├── commodity_map.py
│   ├── car_types.py
│   ├── dispatcher.py
│   ├── session.py
│   ├── automation.py
│   ├── uploads.py
│   ├── settings.py      # Tenant-level AI settings + operator invites
│   ├── operations.py
│   ├── export_import.py
│   ├── webhooks.py      # Patreon webhook handler (unauthenticated)
│   └── admin_keys.py    # Access key CRUD + /redeem + renewal reminders
├── middleware/
│   └── tenant.py        # Host-header → tenant resolution middleware
├── admin/
│   ├── provisioning.py          # provision/suspend/reactivate/extend/delete tenant; welcome email
│   ├── provision_tenant.py      # CLI: python -m admin.provision_tenant
│   └── migrate_all_tenants.py   # CLI: python -m admin.migrate_all_tenants
├── alembic/             # Database migrations
│   └── versions/
├── scripts/
│   ├── hooks/pre-commit         # Git pre-commit hook
│   └── supabase_init.sql        # One-time Supabase setup SQL
├── static/              # CSS and JavaScript
├── templates/           # HTML template
├── tests/               # Pytest test suite
├── Dockerfile
├── fly.toml
└── .env.example         # Configuration template
```

---

## UI design (Figma)

The visual design is driven by CSS custom properties defined in `static/style.css`. All colours, border radii, and key surface values are named variables, making them directly mappable to Figma Variables for iterative design work.

### Design token reference

| Figma variable | CSS property | Current value |
|---|---|---|
| `brand/accent` | `--rail-accent` | `#c0392b` |
| `brand/accent-bg` | `--rail-accent-bg` | `#fdf3f2` |
| `brand/dark` | `--rail-dark` | `#2c3e50` |
| `brand/light` | `--rail-light` | `#ecf0f1` |
| `brand/red` | `--rail-red` | `#e74c3c` |
| `brand/green` | `--rail-green` | `#5c7a3e` |
| `surface/bg-muted` | `--bg-muted` | `#f4f4f4` |
| `surface/border-light` | `--border-light` | `#ddd` |
| `surface/border-muted` | `--border-muted` | `#aaa` |
| `surface/border-subtle` | `--border-subtle` | `#eee` |
| `text/muted` | `--text-muted` | `#888` |
| `text/secondary` | `--text-secondary` | `#555` |
| `text/light` | `--text-light` | `#777` |
| `text/strong` | `--text-strong` | `#333` |
| `badge/blue` | `--badge-blue` | `#2980b9` |
| `badge/green` | `--badge-green` | `#27ae60` |
| `badge/purple` | `--badge-purple` | `#8e44ad` |
| `badge/orange` | `--badge-orange` | `#d68910` |
| `badge/muted-bg` | `--badge-muted-bg` | `#bdc3c7` |
| `radius/card` | `--card-radius` | `8px` |

**Fonts:** body uses *Red Rose* (weights 300–700), headers use *Montserrat Alternates* (weights 400–900), both loaded from Google Fonts.

### Setting up the Figma file

1. Create a **Variables** collection named `Rail Theme` and add each row from the table above, grouped by prefix (`brand/`, `surface/`, `text/`, `badge/`, `radius/`)
2. Create **Text Styles**: `Body/Default` (Red Rose 400, 1rem) and `Brand/Header` (Montserrat Alternates 700)
3. Build components for: car card, navigation tabs, waybill badge, dialog template, toast notification — using Auto Layout and the Variables you just defined

### Iteration workflow

1. Adjust Variable values in Figma
2. Open Dev Mode → Variables panel to read the updated hex values
3. Update the matching `--variable-name` in `static/style.css :root`
4. Commit

For an automated token export, install the [Tokens Studio for Figma](https://tokens.studio) plugin — it can export a `tokens.json` that a small script can apply directly to `style.css`.

---

## License

[MIT](LICENSE) — Copyright 2026 David Dalzell
