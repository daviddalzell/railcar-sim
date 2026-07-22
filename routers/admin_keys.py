# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Admin key management and public access-key redemption endpoints."""

import hashlib
import hmac
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

logger = logging.getLogger("waypoint")

router = APIRouter(tags=["admin"])


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _verify_admin_cookie(admin_session: str | None) -> None:
    admin_pw = os.environ.get("ADMIN_PASSWORD")
    if not admin_pw:
        raise HTTPException(503, "ADMIN_PASSWORD not configured")
    if not admin_session:
        raise HTTPException(401, "Not authenticated")
    try:
        ts_str, sig = admin_session.rsplit(".", 1)
    except ValueError:
        raise HTTPException(401, "Invalid session")
    secret = admin_pw.encode()
    expected = hmac.new(secret, ts_str.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(401, "Invalid session")
    if time.time() - int(ts_str) > 86400:
        raise HTTPException(401, "Session expired")


def _make_code() -> str:
    """Generate a human-readable key like RAIL-A1B2-C3D4."""
    raw = secrets.token_urlsafe(6).upper().replace("-", "").replace("_", "")[:8]
    return f"RAIL-{raw[:4]}-{raw[4:]}"


# ── Admin: key management ─────────────────────────────────────────────────────

class CreateKeyRequest(BaseModel):
    tenant_slug: str
    tenant_name: str
    admin_email: str
    duration_days: int = 365
    notes: str | None = None


@router.get("/admin/keys")
def list_keys(admin_session: str | None = Cookie(default=None)):
    _verify_admin_cookie(admin_session)
    from database import engine
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, code, tenant_slug, tenant_name, admin_email, duration_days,
                   notes, created_at, redeemed_at, redeemed_by_email
            FROM public.access_keys
            ORDER BY created_at DESC
        """)).mappings().all()
    return [dict(r) for r in rows]


@router.post("/admin/keys", status_code=201)
def create_key(data: CreateKeyRequest, admin_session: str | None = Cookie(default=None)):
    _verify_admin_cookie(admin_session)
    from admin.provisioning import validate_slug
    try:
        validate_slug(data.tenant_slug)
    except ValueError as e:
        raise HTTPException(400, str(e))

    code = _make_code()
    from database import engine
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO public.access_keys
                (code, tenant_slug, tenant_name, admin_email, duration_days, notes, created_at)
            VALUES (:code, :slug, :name, :email, :days, :notes, NOW())
        """), {
            "code": code, "slug": data.tenant_slug, "name": data.tenant_name,
            "email": data.admin_email, "days": data.duration_days, "notes": data.notes,
        })
    logger.info("Access key created: %s → %s (%s)", code, data.tenant_slug, data.admin_email)
    return {"code": code, "tenant_slug": data.tenant_slug}


@router.delete("/admin/keys/{code}", status_code=204)
def revoke_key(code: str, admin_session: str | None = Cookie(default=None)):
    _verify_admin_cookie(admin_session)
    from database import engine
    with engine.begin() as conn:
        result = conn.execute(text("""
            DELETE FROM public.access_keys
            WHERE code = :code AND redeemed_at IS NULL
        """), {"code": code})
    if result.rowcount == 0:
        raise HTTPException(404, "Key not found or already redeemed")


# ── Admin: tenant management ──────────────────────────────────────────────────

@router.get("/admin/tenants")
def list_tenants(admin_session: str | None = Cookie(default=None)):
    _verify_admin_cookie(admin_session)
    from database import SessionLocal
    from models import Tenant
    db = SessionLocal()
    try:
        tenants = db.query(Tenant).order_by(Tenant.created_at).all()
        return [
            {
                "id": t.id,
                "slug": t.slug,
                "name": t.name,
                "subscription_status": t.subscription_status,
                "subscription_expires_at": t.subscription_expires_at.isoformat() if t.subscription_expires_at else None,
                "patreon_member_id": t.patreon_member_id,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tenants
        ]
    finally:
        db.close()


class ExtendRequest(BaseModel):
    days: int = 365


@router.post("/admin/tenants/{slug}/extend", status_code=200)
def extend_tenant(slug: str, data: ExtendRequest, admin_session: str | None = Cookie(default=None)):
    _verify_admin_cookie(admin_session)
    from admin.provisioning import extend_tenant_lease
    if not extend_tenant_lease(slug, data.days):
        raise HTTPException(404, "Tenant not found")
    return {"ok": True, "slug": slug, "days_added": data.days}


@router.post("/admin/tenants/{slug}/suspend", status_code=200)
def suspend(slug: str, admin_session: str | None = Cookie(default=None)):
    _verify_admin_cookie(admin_session)
    from admin.provisioning import suspend_tenant
    if not suspend_tenant(slug):
        raise HTTPException(404, "Tenant not found")
    return {"ok": True}


@router.post("/admin/tenants/{slug}/reactivate", status_code=200)
def reactivate(slug: str, admin_session: str | None = Cookie(default=None)):
    _verify_admin_cookie(admin_session)
    from admin.provisioning import reactivate_tenant
    if not reactivate_tenant(slug):
        raise HTTPException(404, "Tenant not found")
    return {"ok": True}


@router.delete("/admin/tenants/{slug}", status_code=204)
def remove_tenant(slug: str, admin_session: str | None = Cookie(default=None)):
    _verify_admin_cookie(admin_session)
    from admin.provisioning import delete_tenant
    if not delete_tenant(slug):
        raise HTTPException(404, "Tenant not found")


@router.post("/admin/send-renewal-reminders", status_code=200)
def send_renewal_reminders(admin_session: str | None = Cookie(default=None)):
    _verify_admin_cookie(admin_session)
    from database import engine
    import smtplib
    from email.message import EmailMessage
    from email import policy

    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_from = os.environ.get("SMTP_FROM", smtp_user)
    app_url = os.environ.get("APP_URL", "https://waypoint-ops.com")

    if not smtp_user:
        raise HTTPException(503, "SMTP_USER not configured")

    smtp_pass = "".join(c for c in smtp_pass if ord(c) > 32 and ord(c) < 127)
    now = datetime.now(timezone.utc)

    # Find tenants expiring in ≤30 days that are still active/suspended
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT t.slug, t.name, t.subscription_expires_at,
                   m.email AS admin_email
            FROM public.tenants t
            LEFT JOIN public.tenant_members m
                ON m.tenant_slug = t.slug AND m.role = 'admin' AND m.is_active = true
            WHERE t.subscription_expires_at IS NOT NULL
              AND t.subscription_expires_at <= NOW() + INTERVAL '30 days'
              AND t.subscription_expires_at > NOW()
              AND t.subscription_status IN ('active', 'suspended')
              AND m.email IS NOT NULL
        """)).mappings().all()

    sent = 0
    errors = []
    for row in rows:
        days_left = (row["subscription_expires_at"].replace(tzinfo=timezone.utc) - now).days
        urgency = "⚠️ Urgent: " if days_left <= 7 else ""
        subject = f"{urgency}Your Waypoint layout expires in {days_left} days — {row['name']}"
        slug_prefix = row["slug"] + "."
        tenant_url = app_url.replace("://", "://" + slug_prefix)
        body = (
            f"<p>Your Waypoint layout <strong>{row['name']}</strong> expires in "
            f"<strong>{days_left} days</strong> "
            f"({row['subscription_expires_at'].strftime('%B %d, %Y')}).</p>"
            f"<p>To renew, reply to this email or message David via Venmo.</p>"
            f'<p><a href="{tenant_url}">Visit your layout</a></p>'
        )
        try:
            msg = EmailMessage(policy=policy.SMTP)
            msg["Subject"] = subject
            msg["From"] = smtp_from
            msg["To"] = row["admin_email"]
            msg.set_content(body, subtype="html", charset="utf-8")
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as srv:
                srv.starttls()
                srv.login(smtp_user, smtp_pass)
                srv.send_message(msg)
            sent += 1
        except Exception as e:
            errors.append(f"{row['slug']}: {e}")

    return {"sent": sent, "errors": errors}


# ── Public: redeem access key ─────────────────────────────────────────────────

class RedeemRequest(BaseModel):
    code: str


@router.post("/redeem", status_code=200)
def redeem_key(data: RedeemRequest):
    from database import engine
    from admin.provisioning import provision_tenant, send_welcome_email

    code = data.code.strip().upper()
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT * FROM public.access_keys WHERE code = :code
        """), {"code": code}).mappings().first()

    if not row:
        raise HTTPException(404, "Invalid access code. Check the code and try again.")
    if row["redeemed_at"] is not None:
        raise HTTPException(409, "This access code has already been used.")

    slug = row["tenant_slug"]
    name = row["tenant_name"]
    email = row["admin_email"]
    duration = row["duration_days"]
    expires_at = datetime.now(timezone.utc) + timedelta(days=duration)

    try:
        result = provision_tenant(
            slug=slug,
            name=name,
            admin_email=email,
            expires_at=expires_at,
        )
    except ValueError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        logger.error("Redemption failed for code %s: %s", code, e)
        raise HTTPException(500, f"Provisioning failed: {e}")

    # Mark code redeemed
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE public.access_keys
            SET redeemed_at = NOW(), redeemed_by_email = :email
            WHERE code = :code
        """), {"code": code, "email": email})

    # Send welcome email (non-fatal)
    send_welcome_email(email, slug, name, expires_at)

    app_url = os.environ.get("APP_URL", "https://waypoint-ops.com")
    base = app_url.split("://", 1)[-1].removeprefix("www.")
    tenant_url = f"https://{slug}.{base}"
    logger.info("Access key %s redeemed → %s (%s)", code, slug, email)
    return {"ok": True, "tenant_url": tenant_url, "slug": slug, "name": name}
