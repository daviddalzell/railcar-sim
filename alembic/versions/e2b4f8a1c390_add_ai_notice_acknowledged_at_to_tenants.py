# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Add ai_notice_acknowledged_at to tenants

Revision ID: e2b4f8a1c390
Revises: d1a9f3e7c841
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = "e2b4f8a1c390"
down_revision = "d1a9f3e7c841"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("ai_notice_acknowledged_at", sa.DateTime(), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("tenants", "ai_notice_acknowledged_at", schema="public")
