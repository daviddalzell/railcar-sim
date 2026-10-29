# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Rename switching_areas → locations and locations → tracks.

Also renames the switching_area_id FK column to location_id in both
the tracks table (formerly locations) and dispatch_plan.

Revision ID: b2c4a9e1f836
Revises: f3b1c9e2a847
"""

from alembic import op

revision = "b2c4a9e1f836"
down_revision = "f3b1c9e2a847"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename old `locations` table → `tracks` first so the name "locations"
    # is free for the old `switching_areas` rename in the next step.
    op.rename_table("locations", "tracks")
    op.rename_table("switching_areas", "locations")

    # Rename the FK column on tracks (formerly switching_area_id → location_id)
    op.alter_column("tracks", "switching_area_id", new_column_name="location_id")

    # Rename the FK column on dispatch_plan
    op.alter_column("dispatch_plan", "switching_area_id", new_column_name="location_id")


def downgrade() -> None:
    op.alter_column("dispatch_plan", "location_id", new_column_name="switching_area_id")
    op.alter_column("tracks", "location_id", new_column_name="switching_area_id")
    op.rename_table("locations", "switching_areas")
    op.rename_table("tracks", "locations")
