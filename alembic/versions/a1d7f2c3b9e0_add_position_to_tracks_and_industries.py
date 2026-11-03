# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Add position to locations, tracks, and industries for manual ordering.

Revision ID: a1d7f2c3b9e0
Revises: b2c4a9e1f836
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa

revision = "a1d7f2c3b9e0"
down_revision = "b2c4a9e1f836"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Unqualified names resolve via the per-schema search_path (see alembic/env.py),
    # so this runs once per schema (public/demo + each tenant).
    op.add_column("locations", sa.Column("position", sa.Integer(), nullable=True))
    op.add_column("tracks", sa.Column("position", sa.Integer(), nullable=True))
    op.add_column("industries", sa.Column("position", sa.Integer(), nullable=True))
    # Backfill a deterministic initial order (by id) so siblings keep insertion order.
    op.execute(sa.text("UPDATE locations SET position = id WHERE position IS NULL"))
    op.execute(sa.text("UPDATE tracks SET position = id WHERE position IS NULL"))
    op.execute(sa.text("UPDATE industries SET position = id WHERE position IS NULL"))


def downgrade() -> None:
    op.drop_column("industries", "position")
    op.drop_column("tracks", "position")
    op.drop_column("locations", "position")
