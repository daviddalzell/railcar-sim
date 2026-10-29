# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Clone the demo-template tenant schema into the public (demo) schema.

Called by POST /admin/reset-demo when a demo-template tenant exists and has cars.
Returns True on success, False if the template is absent or empty (caller falls
back to the hardcoded seed_demo()).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Tables in FK-safe insert order; movement_logs is handled separately (regenerated fresh).
_TABLES = [
    "car_types",
    "locations",
    "tracks",
    "industries",
    "commodity_car_type_map",
    "cars",
    "waybills",
    "dispatch_plan",
    "layout_settings",
]


def clone_to_demo(template_schema: str = "t_demo_template") -> bool:
    """Copy template_schema → public schema and return True, or return False to trigger fallback."""
    from dotenv import load_dotenv
    load_dotenv()

    from database import engine
    from sqlalchemy import text

    # Check template has cars before committing to a destructive truncate
    try:
        with engine.connect() as conn:
            count = conn.execute(
                text(f'SELECT COUNT(*) FROM "{template_schema}".cars')
            ).scalar()
        if not count:
            print(f"[clone_demo] {template_schema}.cars is empty — falling back to hardcoded seed")
            return False
    except Exception as exc:
        print(f"[clone_demo] Cannot read {template_schema}: {exc} — falling back to hardcoded seed")
        return False

    # Purge demo tenant's uploaded photos before wiping the car rows
    try:
        from sqlalchemy import text as _text
        with engine.connect() as _conn:
            row = _conn.execute(
                _text("SELECT schema_name FROM public.tenants WHERE slug = 'demo' LIMIT 1")
            ).fetchone()
        if row and row[0]:
            import storage as _storage
            purged = _storage.purge_folder(row[0])
            if purged:
                print(f"[clone_demo] Purged {purged} uploaded file(s) from storage")
    except Exception as _exc:
        print(f"[clone_demo] Storage purge skipped: {_exc}")

    with engine.begin() as conn:
        # Truncate all public schema tables in one statement (CASCADE handles FKs,
        # RESTART IDENTITY resets sequences to 1 ready for the incoming rows).
        all_tables = ", ".join(
            f'public."{t}"' for t in reversed(_TABLES + ["movement_logs"])
        )
        conn.execute(text(f"TRUNCATE {all_tables} RESTART IDENTITY CASCADE"))

        for tname in _TABLES:
            conn.execute(text(
                f'INSERT INTO public."{tname}" SELECT * FROM "{template_schema}"."{tname}"'
            ))
            # Push the sequence past the highest inserted ID so new rows don't collide.
            conn.execute(text(f"""
                SELECT setval(
                    pg_get_serial_sequence('public.{tname}', 'id'),
                    COALESCE((SELECT MAX(id) FROM public."{tname}"), 1),
                    true
                )
            """))

    print(f"[clone_demo] Cloned {template_schema} → public ({count} cars)")
    return True
