# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Add data plate fields to cars

Revision ID: ab7ef69741a9
Revises: 5fde0532342c
Create Date: 2026-11-18
"""
from alembic import op

revision = "ab7ef69741a9"
down_revision = "5fde0532342c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE cars ADD COLUMN IF NOT EXISTS light_weight INTEGER")
    op.execute("ALTER TABLE cars ADD COLUMN IF NOT EXISTS load_limit INTEGER")
    op.execute("ALTER TABLE cars ADD COLUMN IF NOT EXISTS capacity INTEGER")
    op.execute("ALTER TABLE cars ADD COLUMN IF NOT EXISTS built_date VARCHAR")
    op.execute("ALTER TABLE cars ADD COLUMN IF NOT EXISTS reweigh_date VARCHAR")
    op.execute("ALTER TABLE cars ADD COLUMN IF NOT EXISTS reweigh_location VARCHAR")
    op.execute("ALTER TABLE cars ADD COLUMN IF NOT EXISTS cots_date VARCHAR")
    op.execute("ALTER TABLE cars ADD COLUMN IF NOT EXISTS cots_location VARCHAR")


def downgrade() -> None:
    op.execute("ALTER TABLE cars DROP COLUMN IF EXISTS cots_location")
    op.execute("ALTER TABLE cars DROP COLUMN IF EXISTS cots_date")
    op.execute("ALTER TABLE cars DROP COLUMN IF EXISTS reweigh_location")
    op.execute("ALTER TABLE cars DROP COLUMN IF EXISTS reweigh_date")
    op.execute("ALTER TABLE cars DROP COLUMN IF EXISTS built_date")
    op.execute("ALTER TABLE cars DROP COLUMN IF EXISTS capacity")
    op.execute("ALTER TABLE cars DROP COLUMN IF EXISTS load_limit")
    op.execute("ALTER TABLE cars DROP COLUMN IF EXISTS light_weight")
