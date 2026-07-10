# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

import os
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)

# Lazily initialised so the app starts without Supabase env vars set (local dev)
_supabase = None


def _get_supabase():
    global _supabase
    if _supabase is None:
        from supabase import create_client
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_KEY", "")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set when AUTH_DISABLED is not set")
        _supabase = create_client(url, key)
    return _supabase


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> dict:
    """Validate the Supabase JWT and return the user dict.

    When AUTH_DISABLED is set (local dev), returns a synthetic admin user
    without touching Supabase at all.
    """
    if os.environ.get("AUTH_DISABLED"):
        return {"id": "local", "email": "local@dev", "role": "admin", "tenant_slug": "local"}

    tenant = getattr(request.state, "tenant", None)
    if getattr(tenant, "slug", None) == "demo":
        return {"id": "demo", "email": "demo@waypoint-ops.com", "role": "admin", "tenant_slug": "demo"}

    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        supabase = _get_supabase()
        response = supabase.auth.get_user(credentials.credentials)
        user = response.user
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Check if this user has been explicitly revoked from this tenant
    tenant_slug = getattr(getattr(request.state, "tenant", None), "slug", None)
    if tenant_slug:
        try:
            from database import engine, _is_sqlite
            from sqlalchemy import text as _text
            if not _is_sqlite:
                with engine.connect() as conn:
                    revoked = conn.execute(_text("""
                        SELECT 1 FROM public.tenant_members
                        WHERE supabase_user_id = :uid AND tenant_slug = :slug AND is_active = false
                        LIMIT 1
                    """), {"uid": str(user.id), "slug": tenant_slug}).fetchone()
                    if revoked:
                        raise HTTPException(status_code=403, detail="Access revoked")
        except HTTPException:
            raise
        except Exception:
            pass  # DB check failure is non-fatal; let the request through

    meta = user.user_metadata or {}
    return {
        "id": user.id,
        "email": user.email,
        "role": meta.get("role", "operator"),
        "tenant_slug": meta.get("tenant_slug", ""),
    }


async def require_admin(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def is_demo(request: Request) -> bool:
    """Return True when the request is for the public demo tenant."""
    tenant = getattr(request.state, "tenant", None)
    return getattr(tenant, "slug", None) == "demo"


# Convenience type aliases for use in router signatures
CurrentUser = Annotated[dict, Depends(get_current_user)]
AdminUser = Annotated[dict, Depends(require_admin)]
