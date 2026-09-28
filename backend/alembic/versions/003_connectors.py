"""Connector credentials, folder subscriptions, sync runs, stable external ids.

Revision ID: 003_connectors
Revises: 002_auth_refresh
Create Date: 2026-09-12
"""

from __future__ import annotations

from alembic import op

revision = "003_connectors"
down_revision = "002_auth_refresh"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "oauth_states",
    "connector_credentials",
    "source_subscriptions",
    "sync_runs",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE oauth_states (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            user_id UUID NOT NULL REFERENCES users(id),
            workspace_id UUID REFERENCES workspaces(id),
            connector_type VARCHAR(64) NOT NULL,
            state VARCHAR(128) NOT NULL UNIQUE,
            redirect_uri TEXT,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE connector_credentials (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            source_id UUID NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
            encrypted_access_token TEXT NOT NULL,
            encrypted_refresh_token TEXT,
            expires_at TIMESTAMPTZ,
            scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
            account_label VARCHAR(512),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (source_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE source_subscriptions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            workspace_id UUID NOT NULL REFERENCES workspaces(id),
            source_id UUID NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
            external_location_id VARCHAR(512) NOT NULL,
            external_location_name VARCHAR(512) NOT NULL,
            include_subfolders BOOLEAN NOT NULL DEFAULT true,
            file_filters JSONB NOT NULL DEFAULT '["pdf","md","txt"]'::jsonb,
            sync_mode VARCHAR(32) NOT NULL DEFAULT 'incremental',
            schedule VARCHAR(64) NOT NULL DEFAULT 'manual',
            status VARCHAR(32) NOT NULL DEFAULT 'active',
            acl JSONB NOT NULL DEFAULT '{}'::jsonb,
            last_sync_at TIMESTAMPTZ,
            next_sync_at TIMESTAMPTZ,
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (source_id, external_location_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE sync_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            subscription_id UUID NOT NULL REFERENCES source_subscriptions(id) ON DELETE CASCADE,
            status VARCHAR(32) NOT NULL DEFAULT 'queued',
            trigger VARCHAR(32) NOT NULL DEFAULT 'manual',
            files_discovered INTEGER NOT NULL DEFAULT 0,
            files_added INTEGER NOT NULL DEFAULT 0,
            files_updated INTEGER NOT NULL DEFAULT 0,
            files_deleted INTEGER NOT NULL DEFAULT 0,
            files_skipped INTEGER NOT NULL DEFAULT 0,
            files_failed INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS subscription_id UUID REFERENCES source_subscriptions(id)")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS external_revision VARCHAR(255)")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS external_status VARCHAR(32) NOT NULL DEFAULT 'active'")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_source_file
        ON documents (tenant_id, source_id, source_file_id)
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_source_subscriptions_workspace ON source_subscriptions (tenant_id, workspace_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sync_runs_subscription ON sync_runs (tenant_id, subscription_id)")

    for table in TENANT_TABLES:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = app_security.current_tenant_id())
            WITH CHECK (tenant_id = app_security.current_tenant_id())
            """
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_documents_source_file")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS external_status")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS external_revision")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS subscription_id")
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"DROP TABLE IF EXISTS {table}")
