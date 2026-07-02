# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Reset a tenant's operational data back to defaults.

Truncates all tenant tables (cars, waybills, locations, industries, etc.)
and reseeds car types. The tenants registry (public.tenants) is never touched.

Usage:
    # Reset by slug (uses the tenant's schema_name from the DB):
    python -m admin.reset_tenant --slug preview

    # Reset the public schema directly (clears wrongly-routed data):
    python -m admin.reset_tenant --schema public

Add --yes to skip the confirmation prompt.
"""

import argparse
import sys


TENANT_TABLES = [
    # Order matters: FK dependents first
    "movement_logs",
    "dispatch_plan",
    "waybills",
    "cars",
    "industries",
    "locations",
    "switching_areas",
    "commodity_car_type_map",
    "car_types",
    "session_clock",
    "layout_settings",
]


def reset(schema: str, yes: bool = False) -> None:
    from dotenv import load_dotenv
    load_dotenv()

    from database import engine, _is_sqlite, SessionLocal
    from sqlalchemy import text

    if _is_sqlite:
        raise RuntimeError("reset_tenant requires Postgres — set DATABASE_URL")

    if not yes:
        answer = input(
            f"This will DELETE ALL DATA in schema '{schema}'. Type the schema name to confirm: "
        )
        if answer.strip() != schema:
            print("Aborted.")
            sys.exit(0)

    with engine.begin() as conn:
        conn.execute(text(f'SET search_path TO "{schema}", public'))

        for table in TENANT_TABLES:
            conn.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
            print(f"  truncated {table}")

        # Reset sequences to 1
        for table in TENANT_TABLES:
            conn.execute(text(
                f"ALTER SEQUENCE IF EXISTS {table}_id_seq RESTART WITH 1"
            ))

    # Reseed car types and default images
    db = SessionLocal()
    try:
        from database import DEFAULT_CAR_TYPES
        from models import CarType
        from pathlib import Path

        conn2 = db.connection()
        conn2.execute(text(f'SET search_path TO "{schema}", public'))

        for name in DEFAULT_CAR_TYPES:
            db.add(CarType(name=name))
        db.flush()

        static_dir = Path("static/images/car-types")
        if static_dir.exists():
            for ct in db.query(CarType).all():
                slug = ct.name.replace(" ", "-")
                for ext in (".svg", ".png", ".jpg", ".jpeg", ".webp"):
                    candidate = static_dir / f"{slug}{ext}"
                    if candidate.exists():
                        ct.default_photo_path = str(candidate)
                        break

        db.commit()
        print(f"  reseeded {db.query(CarType).count()} car types")
    finally:
        db.close()

    print(f"Reset complete: schema '{schema}' is clean.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset a tenant's data to defaults")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--slug", help="Tenant slug (looks up schema_name from DB)")
    group.add_argument("--schema", help="Schema name directly (e.g. public, t_preview)")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    if args.slug:
        from dotenv import load_dotenv
        load_dotenv()
        from database import SessionLocal
        from models import Tenant
        db = SessionLocal()
        try:
            tenant = db.query(Tenant).filter(Tenant.slug == args.slug).first()
            if not tenant:
                print(f"No tenant found with slug '{args.slug}'")
                sys.exit(1)
            schema = tenant.schema_name
        finally:
            db.close()
    else:
        schema = args.schema

    reset(schema, yes=args.yes)


if __name__ == "__main__":
    main()
