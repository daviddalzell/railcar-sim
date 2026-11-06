# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Add excluded_ids_json to dispatch_plan

Revision ID: 46a8e3bd6905
Revises: 5fde0532342c
Create Date: 2026-11-06
"""
from alembic import op

revision = "46a8e3bd6905"
down_revision = "5fde0532342c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE dispatch_plan ADD COLUMN IF NOT EXISTS excluded_ids_json VARCHAR NOT NULL DEFAULT '[]'")


def downgrade() -> None:
    op.execute("ALTER TABLE dispatch_plan DROP COLUMN IF EXISTS excluded_ids_json")
