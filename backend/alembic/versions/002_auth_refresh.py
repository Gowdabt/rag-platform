"""Refresh tokens and membership self-read RLS.

Revision ID: 002_auth_refresh
Revises: 001_initial_schema
Create Date: 2026-09-09
"""

from alembic import op

revision = "002_auth_refresh"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_security.current_user_id()
        RETURNS uuid
        LANGUAGE sql
        STABLE
        AS $$
          SELECT NULLIF(current_setting('app.user_id', true), '')::uuid
        $$
        """
    )
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenant_memberships")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON tenant_memberships
        USING (
            tenant_id = app_security.current_tenant_id()
            OR user_id = app_security.current_user_id()
        )
        WITH CHECK (tenant_id = app_security.current_tenant_id())
        """
    )
    op.execute(
        """
        CREATE TABLE refresh_tokens (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS refresh_tokens")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenant_memberships")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON tenant_memberships
        USING (tenant_id = app_security.current_tenant_id())
        WITH CHECK (tenant_id = app_security.current_tenant_id())
        """
    )
