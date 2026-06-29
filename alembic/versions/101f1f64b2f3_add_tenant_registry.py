"""Add public.tenants registry and seed demo tenant

Revision ID: 101f1f64b2f3
Revises: 55397423d9b2
Create Date: 2026-06-29
"""
from alembic import op

revision = "101f1f64b2f3"
down_revision = "55397423d9b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.tenants (
            id               SERIAL PRIMARY KEY,
            slug             VARCHAR UNIQUE NOT NULL,
            name             VARCHAR NOT NULL,
            schema_name      VARCHAR UNIQUE NOT NULL,
            subscription_status VARCHAR NOT NULL DEFAULT 'active',
            subscription_expires_at TIMESTAMP,
            gemini_api_key   VARCHAR,
            anthropic_api_key VARCHAR,
            openai_api_key   VARCHAR,
            vision_provider  VARCHAR,
            created_at       TIMESTAMP DEFAULT NOW()
        )
    """)
    # Seed the initial tenant — existing data lives in the public schema
    op.execute("""
        INSERT INTO public.tenants (slug, name, schema_name, subscription_status)
        VALUES ('demo', 'Demo Layout', 'public', 'active')
        ON CONFLICT (slug) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.tenants")
