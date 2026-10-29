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
    op.create_table(
        "demo_leads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("marketing_opt_in", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        schema="public",
    )


def downgrade() -> None:
    op.drop_table("demo_leads", schema="public")
