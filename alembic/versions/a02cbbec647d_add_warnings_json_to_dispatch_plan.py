# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Add warnings_json to dispatch_plan

Revision ID: a02cbbec647d
Revises: a1d7f2c3b9e0
Create Date: 2026-11-05
"""
from alembic import op

revision = "a02cbbec647d"
down_revision = "a1d7f2c3b9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE dispatch_plan ADD COLUMN IF NOT EXISTS warnings_json VARCHAR NOT NULL DEFAULT '[]'")


def downgrade() -> None:
    op.execute("ALTER TABLE dispatch_plan DROP COLUMN IF EXISTS warnings_json")
