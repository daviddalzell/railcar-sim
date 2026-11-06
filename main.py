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
    admin,
    admin_keys,
    demo_leads,
    feedback,
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

import subprocess as _sp
try:
    _ASSET_VERSION = _sp.check_output(
        ["git", "rev-parse", "--short", "HEAD"], stderr=_sp.DEVNULL
    ).decode().strip()
except Exception:
    _ASSET_VERSION = os.environ.get("FLY_IMAGE_REF", "1").split(":")[-1][:12]


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
            # Backfill missing column default (table may have been created before DEFAULT was added)
            conn.execute(text("""
                ALTER TABLE public.tenant_members
                    ALTER COLUMN is_active SET DEFAULT true
            """))
            # Ensure unique constraint exists (CREATE TABLE IF NOT EXISTS skips this on existing tables)
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS tenant_members_slug_uid_idx
                    ON public.tenant_members (tenant_slug, supabase_user_id)
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS public.access_keys (
                    id SERIAL PRIMARY KEY,
                    code VARCHAR NOT NULL UNIQUE,
                    tenant_slug VARCHAR NOT NULL,
                    tenant_name VARCHAR NOT NULL,
                    admin_email VARCHAR NOT NULL,
                    duration_days INTEGER NOT NULL DEFAULT 365,
                    notes VARCHAR,
                    created_at TIMESTAMP DEFAULT NOW(),
                    redeemed_at TIMESTAMP,
                    redeemed_by_email VARCHAR
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


@app.get("/redeem")
def redeem_page(request: Request):
    """Public access-key redemption page."""
    return templates.TemplateResponse("landing.html", {"request": request, "show_redeem": True})


@app.get("/auth/confirm")
def auth_confirm(request: Request):
    """PKCE invite confirm page — verifies token_hash then redirects to tenant subdomain via JS."""
    return templates.TemplateResponse(
        "index.html", {
            "request": request,
            "vision_label": "",
            "supabase_url": os.environ.get("SUPABASE_URL", ""),
            "supabase_anon_key": os.environ.get("SUPABASE_ANON_KEY", ""),
            "auth_disabled": False,
            "is_demo": False,
        }
    )


@app.get("/signup")
def signup(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})


@app.get("/updates")
def changelog(request: Request):
    return templates.TemplateResponse("changelog.html", {"request": request})


@app.get("/updates/rfc-layout-setup-rename")
def rfc_layout_rename(request: Request):
    return templates.TemplateResponse("rfc_layout_rename.html", {"request": request})


@app.get("/")
def index(request: Request):
    from database import engine, _is_sqlite
    from sqlalchemy import text
    from datetime import date
    provider = os.environ.get("VISION_PROVIDER", "anthropic")
    vision_label = _PROVIDER_LABELS.get(provider, f"{provider} Vision")
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        return templates.TemplateResponse("landing.html", {"request": request})
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
    auth_disabled = bool(os.environ.get("AUTH_DISABLED"))
    return templates.TemplateResponse(
        "index.html", {
            "request": request,
            "vision_label": vision_label,
            # AUTH_DISABLED means "fully isolated local sandbox" — never wire the
            # frontend to real Supabase auth even if .env has real credentials
            # (load_dotenv() loads them unconditionally; AUTH_DISABLED only bypasses
            # backend JWT checks, not this template context, unless gated here).
            "supabase_url": "" if auth_disabled else os.environ.get("SUPABASE_URL", ""),
            "supabase_anon_key": "" if auth_disabled else os.environ.get("SUPABASE_ANON_KEY", ""),
            "auth_disabled": auth_disabled,
            "is_demo": is_demo,
            "asset_version": _ASSET_VERSION,
            "layout_name": getattr(tenant, "name", "") or "",
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
app.include_router(feedback.router,      dependencies=_auth)
# Webhook and SSE endpoints registered without auth
app.include_router(webhooks.router)
app.include_router(session.sse_router)
app.include_router(ops_events.router)
# Admin key management and public redemption — no tenant auth required
app.include_router(admin_keys.router)
app.include_router(demo_leads.router)
# SYNC_SECRET / admin-cookie gated — no tenant auth required
app.include_router(admin.router)
