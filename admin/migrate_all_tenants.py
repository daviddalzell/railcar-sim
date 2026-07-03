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

    # Sync sequences after migrations to guard against any drift
    _sync_sequences(engine, [s for _, s in schemas])


SEQUENCE_TABLES = [
    "cars", "car_types", "locations", "industries", "waybills",
    "movement_logs", "switching_areas", "dispatch_plan",
]


def _sync_sequences(engine, schemas: list) -> None:
    """Advance each table's PK sequence to max(id) so inserts never conflict."""
    from sqlalchemy import text
    with engine.begin() as conn:
        for schema in schemas:
            conn.execute(text(f'SET search_path TO "{schema}", public'))
            for table in SEQUENCE_TABLES:
                max_id = conn.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table}")).scalar()
                conn.execute(
                    text("SELECT setval(pg_get_serial_sequence(:t, :c), :v, true)"),
                    {"t": table, "c": "id", "v": max(max_id, 1)},
                )
    print(f"[migrate] Sequences synced for {len(schemas)} schema(s)")


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
