# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Patreon membership sync — catches webhooks that were missed.

Fetches all active Patreon members for the campaign, then:
  - Provisions tenants for active members who don't have one yet
  - Suspends tenants whose member is no longer an active patron

Required env vars:
  PATREON_ACCESS_TOKEN  Creator access token from Patreon developer portal
  DATABASE_URL          Postgres DSN (set automatically on Fly)

Usage:
  python -m admin.sync_patreon
"""

import logging
import os

import requests

PATREON_API = "https://www.patreon.com/api/oauth2/v2"

logger = logging.getLogger("waypoint.sync_patreon")


def _headers() -> dict:
    token = os.environ.get("PATREON_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("PATREON_ACCESS_TOKEN is not set")
    return {"Authorization": f"Bearer {token}"}


def get_campaign_id() -> str:
    """Fetch the creator's first campaign ID from the Patreon API."""
    resp = requests.get(
        f"{PATREON_API}/campaigns",
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    if not data:
        raise RuntimeError("No Patreon campaigns found for this access token")
    return data[0]["id"]


def fetch_all_members(campaign_id: str) -> list[dict]:
    """Return all campaign members, handling pagination."""
    members = []
    url = (
        f"{PATREON_API}/campaigns/{campaign_id}/members"
        f"?fields[member]=email,full_name,patron_status"
        f"&page[size]=500"
    )
    while url:
        resp = requests.get(url, headers=_headers(), timeout=15)
        resp.raise_for_status()
        body = resp.json()
        members.extend(body.get("data", []))
        url = body.get("links", {}).get("next")
    return members


def sync(dry_run: bool = False) -> dict:
    from dotenv import load_dotenv
    load_dotenv()

    from database import SessionLocal, _is_sqlite
    from models import Tenant
    from admin.provisioning import provision_tenant, slugify, unique_slug, suspend_tenant

    if _is_sqlite:
        raise RuntimeError("sync_patreon requires Postgres — set DATABASE_URL")

    campaign_id = os.environ.get("PATREON_CAMPAIGN_ID") or get_campaign_id()
    logger.info(f"Syncing campaign {campaign_id}")

    members = fetch_all_members(campaign_id)
    logger.info(f"Fetched {len(members)} members from Patreon")

    # Build lookup: patreon_member_id → member dict
    active: dict[str, dict] = {}
    for m in members:
        attrs = m.get("attributes", {})
        if attrs.get("patron_status") == "active_patron":
            active[m["id"]] = {
                "member_id": m["id"],
                "email": attrs.get("email", ""),
                "full_name": attrs.get("full_name", ""),
            }

    db = SessionLocal()
    try:
        existing = db.query(Tenant).filter(Tenant.patreon_member_id.isnot(None)).all()
        existing_by_member_id = {t.patreon_member_id: t for t in existing}
    finally:
        db.close()

    provisioned = []
    suspended = []
    skipped = []

    # Provision active members who have no tenant
    for member_id, member in active.items():
        if member_id in existing_by_member_id:
            skipped.append(member_id)
            continue
        email = member["email"]
        if not email:
            logger.warning(f"Active member {member_id} has no email — skipping")
            continue

        db = SessionLocal()
        try:
            base_slug = slugify(email.split("@")[0])
            if len(base_slug) < 3:
                base_slug = member_id.replace("-", "")[:8]
            slug = unique_slug(base_slug, db)
        finally:
            db.close()

        name = member["full_name"] or email
        logger.info(f"Provisioning missing tenant for {email} (member_id={member_id})")
        if not dry_run:
            try:
                provision_tenant(
                    slug=slug,
                    name=name,
                    admin_email=email,
                    patreon_member_id=member_id,
                )
                provisioned.append(email)
            except Exception as e:
                logger.error(f"Failed to provision {email}: {e}")
        else:
            provisioned.append(f"[dry-run] {email}")

    # Suspend tenants whose Patreon membership is no longer active
    for member_id, tenant in existing_by_member_id.items():
        if member_id in active:
            continue
        if tenant.subscription_status == "suspended":
            continue
        logger.info(f"Suspending tenant {tenant.slug!r} — no longer active on Patreon")
        if not dry_run:
            suspend_tenant(tenant.slug)
        suspended.append(tenant.slug)

    result = {
        "campaign_id": campaign_id,
        "patreon_members": len(members),
        "active_patrons": len(active),
        "provisioned": provisioned,
        "suspended": suspended,
        "skipped": len(skipped),
    }
    logger.info("Sync complete", extra=result)
    return result


if __name__ == "__main__":
    import json
    import sys
    logging.basicConfig(level=logging.INFO)
    dry_run = "--dry-run" in sys.argv
    result = sync(dry_run=dry_run)
    print(json.dumps(result, indent=2))
