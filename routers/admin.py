# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Admin endpoints guarded by SYNC_SECRET (external cron / scripts), plus the
password-gated admin dashboard. Access-key management and public redemption
live in routers/admin_keys.py instead."""

import hashlib
import hmac
import os
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

router = APIRouter(tags=["admin"])
templates = Jinja2Templates(directory="templates")


def _require_sync_secret(request: Request) -> None:
    secret = os.environ.get("SYNC_SECRET")
    if not secret or request.headers.get("X-Sync-Secret") != secret:
        raise HTTPException(403, "Forbidden")


@router.post("/admin/sync-patreon")
def admin_sync_patreon(request: Request):
    _require_sync_secret(request)
    from admin.sync_patreon import sync
    return sync()


@router.post("/admin/trigger-deploy")
def admin_trigger_deploy(request: Request):
    _require_sync_secret(request)
    from admin.trigger_deploy import trigger
    return trigger()


@router.post("/admin/reset-demo")
def admin_reset_demo(request: Request):
    _require_sync_secret(request)
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


@router.get("/admin/user-stats")
def admin_user_stats(request: Request):
    _require_sync_secret(request)

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


@router.post("/admin/provision-demo-template")
def admin_provision_demo_template(request: Request):
    _require_sync_secret(request)
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


@router.get("/admin/dashboard")
def admin_dashboard(request: Request):
    """Admin dashboard — cookie-gated, serves admin.html."""
    return templates.TemplateResponse("admin.html", {"request": request})


@router.post("/admin/login")
async def admin_login(request: Request):
    """Validate ADMIN_PASSWORD and set a signed session cookie."""
    admin_pw = os.environ.get("ADMIN_PASSWORD")
    if not admin_pw:
        raise HTTPException(503, "ADMIN_PASSWORD not configured")
    body = await request.json()
    if body.get("password") != admin_pw:
        raise HTTPException(403, "Incorrect password")
    secret = admin_pw.encode()
    ts = str(int(time.time()))
    sig = hmac.new(secret, ts.encode(), hashlib.sha256).hexdigest()
    token = f"{ts}.{sig}"
    resp = JSONResponse({"ok": True})
    resp.set_cookie("admin_session", token, httponly=True, samesite="lax", max_age=86400)
    return resp
