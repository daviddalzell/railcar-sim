# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Add patreon_member_id to public.tenants

Revision ID: a3f8c2e1d094
Revises: 101f1f64b2f3
Create Date: 2026-06-29
"""
from alembic import op

revision = "a3f8c2e1d094"
down_revision = "101f1f64b2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE public.tenants
        ADD COLUMN IF NOT EXISTS patreon_member_id VARCHAR
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_tenants_patreon_member_id
        ON public.tenants (patreon_member_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tenants_patreon_member_id")
    op.execute("ALTER TABLE public.tenants DROP COLUMN IF EXISTS patreon_member_id")
