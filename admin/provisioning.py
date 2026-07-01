# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tenant provisioning: create schema, tables, and Supabase auth user."""
import os
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.schema import CreateTable

RESERVED_SLUGS = frozenset([
    "www", "api", "waypoint", "static", "health", "demo",
    "admin", "app", "signup", "webhook", "webhooks",
])
def _get_alembic_head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(cfg)
    return script.get_current_head()


# ── Slug helpers ──────────────────────────────────────────────────────────────

def slugify(text_input: str) -> str:
    slug = text_input.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "tenant"


def validate_slug(slug: str) -> None:
    if len(slug) < 3:
        raise ValueError(f"Slug must be at least 3 characters: {slug!r}")
    if len(slug) > 30:
        raise ValueError(f"Slug must be at most 30 characters: {slug!r}")
    if not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", slug):
        raise ValueError(f"Slug must be lowercase alphanumeric with hyphens (not at start/end): {slug!r}")
    if slug in RESERVED_SLUGS:
        raise ValueError(f"Slug {slug!r} is reserved")


def unique_slug(base: str, db) -> str:
    """Return base slug, or base2, base3, ... until unique."""
    from models import Tenant
    slug = base
    i = 2
    while db.query(Tenant).filter(Tenant.slug == slug).first():
        slug = f"{base}{i}"
        i += 1
    return slug


# ── Core provisioning ─────────────────────────────────────────────────────────

def provision_tenant(
    slug: str,
    name: str,
    admin_email: str,
    patreon_member_id: str | None = None,
) -> dict:
    """
    Provision a new tenant:
    1. Validate slug uniqueness
    2. Create Postgres schema t_{slug}
    3. Create all tenant tables + alembic_version in new schema
    4. Insert Tenant row in public.tenants
    5. Create Supabase Auth admin user (if Supabase configured)
    """
    from database import engine, Base, _is_sqlite, SessionLocal
    from models import Tenant

    if _is_sqlite:
        raise RuntimeError(
            "provision_tenant() requires Postgres — set DATABASE_URL to the Supabase DSN"
        )

    validate_slug(slug)
    schema_name = "t_" + slug.replace("-", "_")

    db = SessionLocal()
    try:
        if db.query(Tenant).filter(Tenant.slug == slug).first():
            raise ValueError(f"Tenant with slug {slug!r} already exists")

        # 1+2. Create schema and all tenant tables
        _create_tenant_schema(engine, Base, schema_name)

        # 3. Insert tenant row
        tenant = Tenant(
            slug=slug,
            name=name,
            schema_name=schema_name,
            subscription_status="active",
            patreon_member_id=patreon_member_id,
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)

        # 4. Create Supabase Auth admin user
        user_id = _create_supabase_user(admin_email, slug, "admin")

        result = {
            "tenant_id": tenant.id,
            "slug": slug,
            "name": name,
            "schema_name": schema_name,
            "admin_email": admin_email,
            "supabase_user_id": user_id,
            "url": f"https://{slug}.waypoint.app",
        }
        print(f"[provision] Tenant {slug!r} provisioned → schema={schema_name}")
        return result

    finally:
        db.close()


def _create_tenant_schema(engine, Base, schema_name: str) -> None:
    """Create schema and all tenant tables within it."""
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
        conn.execute(text(f'SET search_path TO "{schema_name}"'))

        for table in Base.metadata.sorted_tables:
            if table.schema is None:  # skip public.tenants
                conn.execute(CreateTable(table, if_not_exists=True))

        # Create alembic_version table and mark as fully migrated
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR(32) NOT NULL,
                CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
            )
        """))
        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:v) ON CONFLICT DO NOTHING"),
            {"v": _get_alembic_head()},
        )


def _create_supabase_user(email: str, tenant_slug: str, role: str) -> str | None:
    """Invite a user via Supabase Auth. Returns user ID, or None if not configured."""
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    if not (supabase_url and supabase_key):
        print(f"[provision] SUPABASE_URL not set — skipping auth user creation for {email}")
        return None
    try:
        from supabase import create_client
        client = create_client(supabase_url, supabase_key)
        resp = client.auth.admin.invite_user_by_email(
            email,
            options={"data": {"tenant_slug": tenant_slug, "role": role}},
        )
        user_id = getattr(resp.user, "id", None)
        print(f"[provision] Supabase invite sent to {email} (id={user_id})")
        return user_id
    except Exception as e:
        print(f"[provision] Warning: failed to create Supabase user for {email}: {e}")
        return None


# ── Subscription helpers ──────────────────────────────────────────────────────

def suspend_tenant(slug: str, grace_days: int = 30) -> bool:
    from database import SessionLocal
    from models import Tenant
    from middleware.tenant import invalidate_tenant_cache

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
        if not tenant:
            return False
        tenant.subscription_status = "suspended"
        tenant.subscription_expires_at = datetime.now(timezone.utc) + timedelta(days=grace_days)
        db.commit()
        invalidate_tenant_cache(slug)
        print(f"[provision] Tenant {slug!r} suspended (grace until {tenant.subscription_expires_at.date()})")
        return True
    finally:
        db.close()


def reactivate_tenant(slug: str) -> bool:
    from database import SessionLocal
    from models import Tenant
    from middleware.tenant import invalidate_tenant_cache

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
        if not tenant:
            return False
        tenant.subscription_status = "active"
        tenant.subscription_expires_at = None
        db.commit()
        invalidate_tenant_cache(slug)
        print(f"[provision] Tenant {slug!r} reactivated")
        return True
    finally:
        db.close()
