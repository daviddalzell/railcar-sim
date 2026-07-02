# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Run alembic upgrade head for every tenant schema.

Usage:
    python -m admin.migrate_all_tenants

Called automatically by the Dockerfile CMD before uvicorn starts.
"""
import subprocess
import sys


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()

    from sqlalchemy import create_engine, text
    import os

    database_url = os.environ.get("DATABASE_URL")
    if not database_url or database_url.startswith("sqlite"):
        print("[migrate] SQLite detected — running plain alembic upgrade head")
        _alembic_upgrade()
        return

    engine = create_engine(database_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT slug, schema_name FROM public.tenants ORDER BY id")
        ).fetchall()

    schemas = [(row[0], row[1]) for row in rows]

    # Always migrate public first (covers demo tenant and shared tables)
    print("[migrate] Migrating schema: public")
    _alembic_upgrade()

    # Migrate each tenant schema
    for slug, schema_name in schemas:
        if schema_name == "public":
            continue
        print(f"[migrate] Migrating schema: {schema_name} (tenant={slug!r})")
        _alembic_upgrade(schema=schema_name)

    print(f"[migrate] Done — {len(schemas)} tenant(s) migrated")


def _alembic_upgrade(schema: str | None = None) -> None:
    cmd = ["alembic"]
    if schema:
        cmd += ["-x", f"schema={schema}"]
    cmd += ["upgrade", "head"]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"[migrate] ERROR: alembic upgrade failed for schema={schema!r}", file=sys.stderr)
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
