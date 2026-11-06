# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Add max_train_length to layout_settings

Revision ID: 5fde0532342c
Revises: a02cbbec647d
Create Date: 2026-11-06
"""
from alembic import op

revision = "5fde0532342c"
down_revision = "a02cbbec647d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE layout_settings ADD COLUMN IF NOT EXISTS max_train_length INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE layout_settings DROP COLUMN IF EXISTS max_train_length")
