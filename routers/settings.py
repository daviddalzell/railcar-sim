# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.requests import Request

from auth import get_current_user
from database import get_db
from middleware.tenant import invalidate_tenant_cache
from models import Tenant, TenantMember

router = APIRouter(prefix="/api", tags=["settings"])

VALID_PROVIDERS = ("gemini", "anthropic", "openai", "ollama")


class TenantSettingsUpdate(BaseModel):
    name: str | None = None
    vision_provider: str | None = None
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None


class InviteOperatorRequest(BaseModel):
    email: str
    role: str = "operator"


class MemberRoleUpdate(BaseModel):
    role: str


def _supabase_admin():
    import httpx
    from supabase import create_client, ClientOptions
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not (url and key):
        raise HTTPException(503, "Supabase not configured on this server")
    return create_client(url, key, options=ClientOptions(httpx_client=httpx.Client(timeout=15)))


@router.get("/tenant-settings")
def get_settings(request: Request, db: Session = Depends(get_db)):
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
    if data.gemini_api_key is not None:
        row.gemini_api_key = data.gemini_api_key or None
    if data.anthropic_api_key is not None:
        row.anthropic_api_key = data.anthropic_api_key or None
    if data.openai_api_key is not None:
        row.openai_api_key = data.openai_api_key or None

    db.commit()
    invalidate_tenant_cache(tenant_ctx.slug)
    return {"ok": True}


@router.post("/tenant-settings/invite", status_code=200)
def invite_operator(request: Request, data: InviteOperatorRequest, db: Session = Depends(get_db),
                    user: dict = Depends(get_current_user)):
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

    # Check if already an active member (non-fatal if table doesn't exist yet)
    from database import _is_sqlite
    if not _is_sqlite:
        try:
            existing = db.query(TenantMember).filter(
                TenantMember.tenant_slug == tenant_ctx.slug,
                TenantMember.email == data.email,
                TenantMember.is_active == True,
            ).first()
            if existing:
                raise HTTPException(409, f"{data.email} is already a member of this layout")
        except HTTPException:
            raise
        except Exception:
            pass  # table may not exist on first deploy; proceed with invite

    try:
        client = _supabase_admin()
        app_url = os.environ.get("APP_URL", "https://waypoint-ops.com")
        base = app_url.split("://", 1)[-1].lstrip("www.")
        tenant_url = f"https://{tenant_ctx.slug}.{base}"

        # generate_link creates the user + token without sending email,
        # bypassing the redirect_to allowlist entirely.
        link_type = "invite"
        try:
            link_resp = client.auth.admin.generate_link({
                "type": "invite",
                "email": data.email,
                "options": {"data": {"tenant_slug": tenant_ctx.slug, "role": data.role}},
            })
        except Exception as _gen_err:
            # Existing confirmed user — fall back to magic link
            if "registered" in str(_gen_err).lower() or "exists" in str(_gen_err).lower():
                link_type = "magiclink"
                link_resp = client.auth.admin.generate_link({
                    "type": "magiclink",
                    "email": data.email,
                    "options": {"data": {"tenant_slug": tenant_ctx.slug, "role": data.role}},
                })
                client.auth.admin.update_user_by_id(
                    str(link_resp.user.id),
                    {"user_metadata": {"tenant_slug": tenant_ctx.slug, "role": data.role}},
                )
            else:
                raise

        hashed_token = link_resp.properties.hashed_token
        invited_user_id = getattr(link_resp.user, "id", None)

        from urllib.parse import quote as _quote
        confirm_url = (
            f"{app_url}/auth/confirm"
            f"?token_hash={hashed_token}"
            f"&type={link_type}"
            f"&next={_quote(tenant_url, safe='')}"
        )

        smtp_user = os.environ.get("SMTP_USER")
        smtp_pass = os.environ.get("SMTP_PASS")
        if not smtp_user or not smtp_pass:
            raise HTTPException(503, "SMTP_USER and SMTP_PASS not configured — set them as Fly secrets")
        smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_from = os.environ.get("SMTP_FROM", smtp_user)

        if link_type == "invite":
            subject = f"You're invited to join {tenant_ctx.slug} on Waypoint"
            body = (
                f"<p>You've been invited to <strong>{tenant_ctx.slug}</strong> on Waypoint.</p>"
                f'<p><a href="{confirm_url}">Accept invitation &amp; set your password</a></p>'
                f"<p style='color:#999;font-size:12px'>Or copy this link: {confirm_url}</p>"
            )
        else:
            subject = f"You've been added to {tenant_ctx.slug} on Waypoint"
            body = (
                f"<p>You've been added to <strong>{tenant_ctx.slug}</strong> on Waypoint.</p>"
                f'<p><a href="{confirm_url}">Sign in to {tenant_ctx.slug}</a></p>'
                f"<p style='color:#999;font-size:12px'>Or copy this link: {confirm_url}</p>"
            )

        import smtplib as _smtp
        from email.message import EmailMessage as _EM
        msg = _EM()
        msg["Subject"] = subject
        msg["From"] = smtp_from
        msg["To"] = data.email
        msg.set_content(body, subtype="html", charset="utf-8")
        with _smtp.SMTP(smtp_host, smtp_port, timeout=15) as srv:
            srv.starttls()
            srv.login(smtp_user, smtp_pass)
            srv.send_message(msg)

    except HTTPException:
        raise
    except Exception as e:
        msg = str(e)
        if "timed out" in msg.lower() or "timeout" in msg.lower():
            raise HTTPException(503, "Could not reach Supabase — the project may be paused. Resume it in the Supabase dashboard.")
        raise HTTPException(500, f"Failed to send invite: {e}")

    # Sync to tenant_members (non-fatal if table doesn't exist yet)
    if invited_user_id and not _is_sqlite:
        try:
            from database import engine
            from sqlalchemy import text
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO public.tenant_members (tenant_slug, supabase_user_id, email, role, invited_at)
                    VALUES (:slug, :uid, :email, :role, NOW())
                    ON CONFLICT (tenant_slug, supabase_user_id)
                    DO UPDATE SET role = EXCLUDED.role, is_active = true, invited_at = NOW()
                """), {"slug": tenant_ctx.slug, "uid": str(invited_user_id),
                       "email": data.email, "role": data.role})
        except Exception:
            pass

    return {"ok": True, "user_id": invited_user_id}


@router.get("/tenant-settings/members")
def list_members(request: Request, db: Session = Depends(get_db),
                 user: dict = Depends(get_current_user)):
    from auth import is_demo
    if is_demo(request):
        return []
    if (user or {}).get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    tenant_ctx = getattr(request.state, "tenant", None)
    if not tenant_ctx or tenant_ctx.id == 0:
        return []

    from database import _is_sqlite
    if _is_sqlite:
        return []

    # One-time backfill from Supabase if table is empty for this tenant
    try:
        count = db.query(TenantMember).filter(TenantMember.tenant_slug == tenant_ctx.slug).count()
    except Exception:
        return []  # table doesn't exist yet; will be created on next app restart
    if count == 0:
        try:
            client = _supabase_admin()
            users = client.auth.admin.list_users(page=1, per_page=1000)
            from database import engine
            from sqlalchemy import text
            with engine.begin() as conn:
                for u in users:
                    meta = u.user_metadata or {}
                    if meta.get("tenant_slug") == tenant_ctx.slug:
                        conn.execute(text("""
                            INSERT INTO public.tenant_members
                                (tenant_slug, supabase_user_id, email, role, invited_at)
                            VALUES (:slug, :uid, :email, :role, :invited_at)
                            ON CONFLICT (tenant_slug, supabase_user_id) DO NOTHING
                        """), {
                            "slug": tenant_ctx.slug,
                            "uid": str(u.id),
                            "email": u.email or "",
                            "role": meta.get("role", "operator"),
                            "invited_at": u.created_at,
                        })
        except Exception:
            pass  # Backfill failure is non-fatal

    members = (
        db.query(TenantMember)
        .filter(TenantMember.tenant_slug == tenant_ctx.slug)
        .order_by(TenantMember.invited_at)
        .all()
    )
    return [
        {
            "id": m.id,
            "email": m.email,
            "display_name": m.display_name,
            "role": m.role,
            "is_active": m.is_active,
            "invited_at": m.invited_at.isoformat() if m.invited_at else None,
            "joined_at": m.joined_at.isoformat() if m.joined_at else None,
        }
        for m in members
    ]


@router.patch("/tenant-settings/members/me/joined", status_code=200)
def mark_joined(request: Request, db: Session = Depends(get_db),
                user: dict = Depends(get_current_user)):
    from database import _is_sqlite
    if _is_sqlite:
        return {"ok": True}
    tenant_ctx = getattr(request.state, "tenant", None)
    if not tenant_ctx or tenant_ctx.id == 0:
        return {"ok": True}
    uid = (user or {}).get("id")
    if not uid:
        return {"ok": True}
    from datetime import datetime
    member = db.query(TenantMember).filter(
        TenantMember.tenant_slug == tenant_ctx.slug,
        TenantMember.supabase_user_id == str(uid),
        TenantMember.joined_at == None,
    ).first()
    if member:
        member.joined_at = datetime.utcnow()
        db.commit()
    return {"ok": True}


@router.patch("/tenant-settings/members/{member_id}", status_code=200)
def update_member_role(member_id: int, data: MemberRoleUpdate, request: Request,
                       db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    from auth import is_demo
    if is_demo(request):
        raise HTTPException(403, "Disabled in demo")
    if (user or {}).get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    if data.role not in ("operator", "admin"):
        raise HTTPException(400, "Role must be 'operator' or 'admin'")

    tenant_ctx = getattr(request.state, "tenant", None)
    member = db.query(TenantMember).filter(
        TenantMember.id == member_id,
        TenantMember.tenant_slug == tenant_ctx.slug if tenant_ctx else False,
    ).first()
    if not member:
        raise HTTPException(404, "Member not found")

    member.role = data.role
    db.commit()

    # Sync to Supabase metadata so JWT reflects the new role on next refresh
    try:
        client = _supabase_admin()
        client.auth.admin.update_user_by_id(
            member.supabase_user_id,
            {"user_metadata": {"role": data.role, "tenant_slug": tenant_ctx.slug}},
        )
    except Exception:
        pass  # DB update succeeded; Supabase sync failure is non-fatal

    return {"ok": True, "role": data.role}


@router.delete("/tenant-settings/members/{member_id}", status_code=204)
def remove_member(member_id: int, request: Request,
                  db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    from auth import is_demo
    if is_demo(request):
        raise HTTPException(403, "Disabled in demo")
    if (user or {}).get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    tenant_ctx = getattr(request.state, "tenant", None)
    member = db.query(TenantMember).filter(
        TenantMember.id == member_id,
        TenantMember.tenant_slug == tenant_ctx.slug if tenant_ctx else False,
    ).first()
    if not member:
        raise HTTPException(404, "Member not found")

    member.is_active = False
    db.commit()

    # Clear tenant_slug from Supabase metadata so the user's existing JWT stops working
    try:
        client = _supabase_admin()
        client.auth.admin.update_user_by_id(
            member.supabase_user_id,
            {"user_metadata": {"tenant_slug": "", "role": ""}},
        )
    except Exception:
        pass  # DB update succeeded; Supabase sync failure is non-fatal
