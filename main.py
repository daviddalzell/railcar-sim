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
    session._register_loop(asyncio.get_running_loop())
    init_db()
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


@app.get("/signup")
def signup(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})


@app.get("/")
def index(request: Request):
    provider = os.environ.get("VISION_PROVIDER", "anthropic")
    vision_label = _PROVIDER_LABELS.get(provider, f"{provider} Vision")
    return templates.TemplateResponse(
        "index.html", {
            "request": request,
            "vision_label": vision_label,
            "supabase_url": os.environ.get("SUPABASE_URL", ""),
            "supabase_anon_key": os.environ.get("SUPABASE_ANON_KEY", ""),
            "auth_disabled": bool(os.environ.get("AUTH_DISABLED")),
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
