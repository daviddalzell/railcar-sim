# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Add operator_email to movement_logs

Revision ID: c7e91a3f2b05
Revises: a3f8c2e1d094
Create Date: 2026-07-05
"""
from alembic import op

revision = "c7e91a3f2b05"
down_revision = "a3f8c2e1d094"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE movement_logs ADD COLUMN IF NOT EXISTS operator_email VARCHAR")


def downgrade() -> None:
    op.execute("ALTER TABLE movement_logs DROP COLUMN IF EXISTS operator_email")
