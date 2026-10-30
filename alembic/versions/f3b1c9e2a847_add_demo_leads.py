"""add demo_leads table

Revision ID: f3b1c9e2a847
Revises: e2b4f8a1c390
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from alembic import op

revision = "f3b1c9e2a847"
down_revision = "e2b4f8a1c390"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS public.demo_leads (
            id SERIAL PRIMARY KEY,
            email VARCHAR NOT NULL UNIQUE,
            marketing_opt_in BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
        )
    """))


def downgrade() -> None:
    op.drop_table("demo_leads", schema="public")
