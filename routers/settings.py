# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.requests import Request

from auth import get_current_user
from database import get_db
from middleware.tenant import invalidate_tenant_cache
from models import Tenant

router = APIRouter(prefix="/api", tags=["settings"])

VALID_PROVIDERS = ("gemini", "anthropic", "openai", "ollama")


class TenantSettingsUpdate(BaseModel):
    name: str | None = None
    vision_provider: str | None = None
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None


@router.get("/tenant-settings")
def get_settings(request: Request, db: Session = Depends(get_db)):
    import os
    tenant_ctx = getattr(request.state, "tenant", None)
    if not tenant_ctx or tenant_ctx.id == 0:
        return {
            "vision_provider": os.environ.get("VISION_PROVIDER", "gemini"),
            "gemini_key_set": bool(os.environ.get("GEMINI_API_KEY")),
            "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "openai_key_set": bool(os.environ.get("OPENAI_API_KEY")),
            "source": "env",
        }
    row = db.query(Tenant).filter(Tenant.id == tenant_ctx.id).first()
    if not row:
        raise HTTPException(404, "Tenant not found")
    return {
        "name": row.name or "",
        "vision_provider": row.vision_provider or os.environ.get("VISION_PROVIDER", "gemini"),
        "gemini_key_set": bool(row.gemini_api_key or os.environ.get("GEMINI_API_KEY")),
        "anthropic_key_set": bool(row.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")),
        "openai_key_set": bool(row.openai_api_key or os.environ.get("OPENAI_API_KEY")),
        "source": "tenant",
    }


@router.patch("/tenant-settings", status_code=200)
def update_settings(request: Request, data: TenantSettingsUpdate, db: Session = Depends(get_db)):
    from auth import is_demo
    if is_demo(request):
        raise HTTPException(403, "Settings cannot be changed in the demo")
    tenant_ctx = getattr(request.state, "tenant", None)
    if not tenant_ctx or tenant_ctx.id == 0:
        raise HTTPException(400, "Settings cannot be saved in local dev mode — set env vars directly")

    if data.vision_provider is not None and data.vision_provider not in VALID_PROVIDERS:
        raise HTTPException(400, f"Invalid provider. Must be one of: {', '.join(VALID_PROVIDERS)}")

    if data.name is not None and not data.name.strip():
        raise HTTPException(400, "Tenant name cannot be blank")

    row = db.query(Tenant).filter(Tenant.id == tenant_ctx.id).first()
    if not row:
        raise HTTPException(404, "Tenant not found")

    if data.name is not None:
        row.name = data.name.strip()
    if data.vision_provider is not None:
        row.vision_provider = data.vision_provider
    # Empty string clears a key; None means no change
    if data.gemini_api_key is not None:
        row.gemini_api_key = data.gemini_api_key or None
    if data.anthropic_api_key is not None:
        row.anthropic_api_key = data.anthropic_api_key or None
    if data.openai_api_key is not None:
        row.openai_api_key = data.openai_api_key or None

    db.commit()
    invalidate_tenant_cache(tenant_ctx.slug)
    return {"ok": True}


class InviteOperatorRequest(BaseModel):
    email: str
    role: str = "operator"


@router.post("/tenant-settings/invite", status_code=200)
def invite_operator(request: Request, data: InviteOperatorRequest, db: Session = Depends(get_db),
                    user: dict = Depends(get_current_user)):
    import os
    from auth import is_demo
    if is_demo(request):
        raise HTTPException(403, "Invitations are disabled in the demo")
    if (user or {}).get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    tenant_ctx = getattr(request.state, "tenant", None)
    if not tenant_ctx or tenant_ctx.id == 0:
        raise HTTPException(400, "Invitations require a cloud tenant — not available in local dev mode")

    if data.role not in ("operator", "admin"):
        raise HTTPException(400, "Role must be 'operator' or 'admin'")

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    if not (supabase_url and supabase_key):
        raise HTTPException(503, "Supabase not configured on this server")

    try:
        import httpx
        from supabase import create_client, ClientOptions
        client = create_client(supabase_url, supabase_key,
                               options=ClientOptions(httpx_client=httpx.Client(timeout=15)))
        app_url = os.environ.get("APP_URL", "https://waypoint-ops.com")
        # Strip scheme to rebuild with tenant subdomain
        base = app_url.split("://", 1)[-1].lstrip("www.")
        redirect_to = f"https://{tenant_ctx.slug}.{base}/"
        resp = client.auth.admin.invite_user_by_email(
            data.email,
            options={
                "data": {"tenant_slug": tenant_ctx.slug, "role": data.role},
                "redirect_to": redirect_to,
            },
        )
        user_id = getattr(resp.user, "id", None)
        return {"ok": True, "user_id": user_id}
    except Exception as e:
        msg = str(e)
        if "timed out" in msg.lower() or "timeout" in msg.lower():
            raise HTTPException(503, "Could not reach Supabase — the project may be paused. Resume it in the Supabase dashboard.")
        raise HTTPException(500, f"Failed to send invite: {e}")

