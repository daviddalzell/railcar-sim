# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Add is_priority to waybills

Revision ID: d1a9f3e7c841
Revises: c7e91a3f2b05
Create Date: 2026-10-15
"""
from alembic import op

revision = "d1a9f3e7c841"
down_revision = "c7e91a3f2b05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE waybills ADD COLUMN IF NOT EXISTS is_priority BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE waybills DROP COLUMN IF EXISTS is_priority")
