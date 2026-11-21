# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Add industry intensity and car demurrage fields

Revision ID: a33a51517aea
Revises: ab7ef69741a9
Create Date: 2026-11-20
"""
from alembic import op

revision = "a33a51517aea"
down_revision = "ab7ef69741a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE industries ADD COLUMN IF NOT EXISTS avg_monthly_carloads INTEGER")
    op.execute("ALTER TABLE industries ADD COLUMN IF NOT EXISTS dwell_multiplier FLOAT DEFAULT 1.0 NOT NULL")
    op.execute("ALTER TABLE commodity_car_type_map ADD COLUMN IF NOT EXISTS base_dwell_turns INTEGER DEFAULT 1 NOT NULL")
    op.execute("ALTER TABLE cars ADD COLUMN IF NOT EXISTS dwell_turns_required INTEGER DEFAULT 0 NOT NULL")
    op.execute("ALTER TABLE cars ADD COLUMN IF NOT EXISTS dwell_turns_elapsed INTEGER DEFAULT 0 NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE cars DROP COLUMN IF EXISTS dwell_turns_elapsed")
    op.execute("ALTER TABLE cars DROP COLUMN IF EXISTS dwell_turns_required")
    op.execute("ALTER TABLE commodity_car_type_map DROP COLUMN IF EXISTS base_dwell_turns")
    op.execute("ALTER TABLE industries DROP COLUMN IF EXISTS dwell_multiplier")
    op.execute("ALTER TABLE industries DROP COLUMN IF EXISTS avg_monthly_carloads")
