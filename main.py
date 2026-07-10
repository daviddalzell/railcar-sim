# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

import logging

import os

import pillow_heif
pillow_heif.register_heif_opener()
from dotenv import load_dotenv
load_dotenv()

# Structured JSON logging when running in cloud; plain text locally
if os.environ.get("LOG_FORMAT") == "json":
    from pythonjsonlogger.json import JsonFormatter
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.root.handlers = [handler]
    logging.root.setLevel(logging.INFO)
else:
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("waypoint")

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from database import init_db
from middleware.tenant import TenantMiddleware
from vision import get_provider, OllamaVisionProvider

from fastapi import Depends

from auth import get_current_user
from routers import (
    cars,
    waybills,
    locations,
    industries,
    commodity_map,
    car_types,
    dispatcher,
    session,
    automation,
    uploads,
    operations,
    export_import,
    settings,
    webhooks,
    ops_events,
)

_auth = [Depends(get_current_user)]

# Re-export helpers that tests import directly from main
from routers.export_import import parse_csv_cars  # noqa: F401

app = FastAPI(title="Waypoint")
app.add_middleware(TenantMiddleware)
app.mount("/static", StaticFiles(directory="static"), name="static")
# Always mount uploads — locally serves uploaded files; in cloud the dir is
# empty and CDN URLs never route through here, so it's harmless.
from pathlib import Path as _Path
_Path("uploads").mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
async def on_startup():
    import asyncio
    import sse_shared
    sse_shared.register_loop(asyncio.get_running_loop())
    session._register_loop(asyncio.get_running_loop())
    init_db()
    from database import engine, _is_sqlite
    from sqlalchemy import text
    if not _is_sqlite:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS public.page_views (
                    tenant_slug VARCHAR NOT NULL,
                    date DATE NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (tenant_slug, date)
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS public.tenant_members (
                    id SERIAL PRIMARY KEY,
                    tenant_slug VARCHAR NOT NULL,
                    supabase_user_id VARCHAR NOT NULL,
                    email VARCHAR NOT NULL,
                    display_name VARCHAR,
                    role VARCHAR NOT NULL DEFAULT 'operator',
                    is_active BOOLEAN NOT NULL DEFAULT true,
                    invited_at TIMESTAMP DEFAULT NOW(),
                    joined_at TIMESTAMP,
                    UNIQUE (tenant_slug, supabase_user_id)
                )
            """))
    try:
        provider = get_provider()
    except ValueError:
        provider = None
    if isinstance(provider, OllamaVisionProvider):
        provider.ensure_ready()


# ── HTML shell ────────────────────────────────────────────────────────────────

_PROVIDER_LABELS = {
    "anthropic": "Claude Vision",
    "openai": "OpenAI Vision",
    "ollama": f"Ollama ({os.environ.get('OLLAMA_MODEL', 'llava')})",
    "gemini": f"Gemini ({os.environ.get('GEMINI_MODEL', 'gemini-3.1-flash-lite')})",
}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/admin/sync-patreon")
def admin_sync_patreon(request: Request):
    from fastapi import HTTPException
    secret = os.environ.get("SYNC_SECRET")
    if not secret or request.headers.get("X-Sync-Secret") != secret:
        raise HTTPException(403, "Forbidden")
    from admin.sync_patreon import sync
    result = sync()
    return result


@app.post("/admin/reset-demo")
def admin_reset_demo(request: Request):
    from fastapi import HTTPException
    secret = os.environ.get("SYNC_SECRET")
    if not secret or request.headers.get("X-Sync-Secret") != secret:
        raise HTTPException(403, "Forbidden")
    from admin.clone_demo import clone_to_demo
    from admin.seed_demo import regenerate_movement_logs, seed_demo
    cloned = clone_to_demo()
    if cloned:
        from database import SessionLocal
        db = SessionLocal()
        try:
            regenerate_movement_logs(db)
        finally:
            db.close()
        return {"ok": True, "source": "template"}
    seed_demo()
    return {"ok": True, "source": "hardcoded"}


@app.get("/admin/user-stats")
def admin_user_stats(request: Request):
    from fastapi import HTTPException
    secret = os.environ.get("SYNC_SECRET")
    if not secret or request.headers.get("X-Sync-Secret") != secret:
        raise HTTPException(403, "Forbidden")

    from database import engine, _is_sqlite, SessionLocal
    from sqlalchemy import text
    from datetime import date, timedelta, datetime as dt
    from models import Tenant

    db = SessionLocal()
    try:
        tenants = db.query(Tenant).order_by(Tenant.created_at).all()
    finally:
        db.close()

    today = date.today()
    thirty_days_ago = today - timedelta(days=30)
    _DEMO_EMAILS = {"local", "dispatcher@mbw.demo"}

    rows = []
    total_views_30d = 0
    total_operators_30d = 0

    for t in tenants:
        views_30d = views_today = 0
        operators_30d = 0

        if not _is_sqlite:
            with engine.connect() as conn:
                r = conn.execute(text("""
                    SELECT
                        COALESCE(SUM(count) FILTER (WHERE date >= :start), 0) AS views_30d,
                        COALESCE(SUM(count) FILTER (WHERE date = :today), 0) AS views_today
                    FROM public.page_views
                    WHERE tenant_slug = :slug
                """), {"slug": t.slug, "start": thirty_days_ago, "today": today}).mappings().one()
                views_30d = int(r["views_30d"])
                views_today = int(r["views_today"])

                if t.schema_name:
                    try:
                        r2 = conn.execute(text(f"""
                            SELECT COUNT(DISTINCT operator_email) AS ops
                            FROM "{t.schema_name}".movement_logs
                            WHERE timestamp >= :start
                              AND operator_email IS NOT NULL
                              AND operator_email != ALL(:skip)
                        """), {"start": dt.combine(thirty_days_ago, dt.min.time()), "skip": list(_DEMO_EMAILS)}).scalar()
                        operators_30d = int(r2 or 0)
                    except Exception:
                        pass

        total_views_30d += views_30d
        total_operators_30d += operators_30d
        rows.append({
            "slug": t.slug,
            "name": t.name,
            "status": t.subscription_status,
            "created_at": t.created_at.date().isoformat() if t.created_at else None,
            "views_last_30d": views_30d,
            "views_today": views_today,
            "operators_last_30d": operators_30d,
        })

    active = sum(1 for t in tenants if t.subscription_status == "active")
    return {
        "generated_at": dt.utcnow().isoformat() + "Z",
        "tenants": rows,
        "summary": {
            "total_tenants": len(tenants),
            "active_tenants": active,
            "total_views_last_30d": total_views_30d,
            "total_operators_last_30d": total_operators_30d,
        },
    }


@app.post("/admin/provision-demo-template")
def admin_provision_demo_template(request: Request):
    from fastapi import HTTPException
    secret = os.environ.get("SYNC_SECRET")
    if not secret or request.headers.get("X-Sync-Secret") != secret:
        raise HTTPException(403, "Forbidden")
    admin_email = os.environ.get("DEMO_TEMPLATE_EMAIL")
    if not admin_email:
        raise HTTPException(400, "DEMO_TEMPLATE_EMAIL env var not set")
    from admin.provisioning import provision_tenant
    try:
        result = provision_tenant(
            slug="demo-template",
            name="Demo Template",
            admin_email=admin_email,
            patreon_member_id=None,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return result


@app.get("/signup")
def signup(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})


@app.get("/")
def index(request: Request):
    from database import engine, _is_sqlite
    from sqlalchemy import text
    from datetime import date
    provider = os.environ.get("VISION_PROVIDER", "anthropic")
    vision_label = _PROVIDER_LABELS.get(provider, f"{provider} Vision")
    tenant = getattr(request.state, "tenant", None)
    slug = getattr(tenant, "slug", None) or "unknown"
    is_demo = slug == "demo"
    if not _is_sqlite:
        try:
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO public.page_views (tenant_slug, date, count)
                    VALUES (:slug, :date, 1)
                    ON CONFLICT (tenant_slug, date)
                    DO UPDATE SET count = page_views.count + 1
                """), {"slug": slug, "date": date.today()})
        except Exception:
            pass
    return templates.TemplateResponse(
        "index.html", {
            "request": request,
            "vision_label": vision_label,
            "supabase_url": os.environ.get("SUPABASE_URL", ""),
            "supabase_anon_key": os.environ.get("SUPABASE_ANON_KEY", ""),
            "auth_disabled": bool(os.environ.get("AUTH_DISABLED")),
            "is_demo": is_demo,
        }
    )


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(cars.router,          dependencies=_auth)
app.include_router(waybills.router,      dependencies=_auth)
app.include_router(locations.router,     dependencies=_auth)
app.include_router(industries.router,    dependencies=_auth)
app.include_router(commodity_map.router, dependencies=_auth)
app.include_router(car_types.router,     dependencies=_auth)
app.include_router(dispatcher.router,    dependencies=_auth)
app.include_router(session.router,       dependencies=_auth)
app.include_router(automation.router,    dependencies=_auth)
app.include_router(uploads.router,       dependencies=_auth)
app.include_router(operations.router,    dependencies=_auth)
app.include_router(export_import.router, dependencies=_auth)
app.include_router(settings.router,      dependencies=_auth)
# Webhook and SSE endpoints registered without auth
app.include_router(webhooks.router)
app.include_router(session.sse_router)
app.include_router(ops_events.router)
