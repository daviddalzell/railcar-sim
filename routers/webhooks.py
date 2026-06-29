"""Patreon webhook handler.

Set PATREON_WEBHOOK_SECRET as a Fly.io secret matching the value in
your Patreon creator portal (Webhooks section).

Handled events:
  members:pledge:create  → provision new tenant
  members:pledge:delete  → suspend tenant (30-day grace period)
  members:pledge:update  → reactivate if patron_status returns to active
"""
import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger("waypoint.webhooks")


def _verify_signature(body: bytes, header: str | None) -> bool:
    secret = os.environ.get("PATREON_WEBHOOK_SECRET", "")
    if not secret:
        logger.warning("PATREON_WEBHOOK_SECRET not set — skipping signature check")
        return True
    if not header:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.md5,
    ).hexdigest()
    return hmac.compare_digest(expected, header)


def _extract_member(payload: dict) -> dict:
    """Pull the fields we care about from the Patreon JSON:API payload."""
    data = payload.get("data", {})
    attrs = data.get("attributes", {})
    rels = data.get("relationships", {})
    user_id = (rels.get("user", {}).get("data") or {}).get("id", "")
    return {
        "member_id": data.get("id", ""),
        "patreon_user_id": user_id,
        "email": attrs.get("email", ""),
        "full_name": attrs.get("full_name", ""),
        "patron_status": attrs.get("patron_status", ""),
    }


@router.post("/patreon")
async def patreon_webhook(request: Request) -> Response:
    body = await request.body()
    sig = request.headers.get("X-Patreon-Signature")

    if not _verify_signature(body, sig):
        raise HTTPException(403, "Invalid signature")

    event = request.headers.get("X-Patreon-Event", "")
    try:
        import json
        payload = json.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    member = _extract_member(payload)
    logger.info("Patreon webhook", extra={"event": event, "member_id": member["member_id"]})

    if event == "members:pledge:create":
        _handle_pledge_create(member)

    elif event == "members:pledge:delete":
        _handle_pledge_delete(member)

    elif event == "members:pledge:update":
        _handle_pledge_update(member)

    # Always return 200 so Patreon doesn't retry
    return Response(status_code=200)


def _handle_pledge_create(member: dict) -> None:
    from database import SessionLocal
    from models import Tenant
    from admin.provisioning import provision_tenant, slugify, unique_slug

    email = member["email"]
    if not email:
        logger.warning("Pledge create with no email — skipping", extra=member)
        return

    # Check if this Patreon member already has a tenant (duplicate webhook)
    db = SessionLocal()
    try:
        existing = db.query(Tenant).filter(
            Tenant.patreon_member_id == member["member_id"]
        ).first()
        if existing:
            logger.info(f"Tenant already exists for Patreon member {member['member_id']!r}")
            return

        base_slug = slugify(email.split("@")[0])
        slug = unique_slug(base_slug, db)
        name = member["full_name"] or email
    finally:
        db.close()

    try:
        result = provision_tenant(
            slug=slug,
            name=name,
            admin_email=email,
            patreon_member_id=member["member_id"],
        )
        logger.info("Tenant provisioned from Patreon", extra=result)
    except Exception as e:
        logger.error(f"Failed to provision tenant for {email}: {e}")


def _handle_pledge_delete(member: dict) -> None:
    from database import SessionLocal
    from models import Tenant
    from admin.provisioning import suspend_tenant

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(
            Tenant.patreon_member_id == member["member_id"]
        ).first()
        if not tenant:
            logger.info(f"No tenant for Patreon member {member['member_id']!r} — nothing to suspend")
            return
        slug = tenant.slug
    finally:
        db.close()

    suspend_tenant(slug)


def _handle_pledge_update(member: dict) -> None:
    if member["patron_status"] != "active_patron":
        return
    from database import SessionLocal
    from models import Tenant
    from admin.provisioning import reactivate_tenant

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(
            Tenant.patreon_member_id == member["member_id"]
        ).first()
        if not tenant or tenant.subscription_status == "active":
            return
        slug = tenant.slug
    finally:
        db.close()

    reactivate_tenant(slug)
