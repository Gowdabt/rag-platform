"""Initial tenant-aware schema with versions, jobs, ACL, audit, RLS.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-09-09
"""

from __future__ import annotations

from alembic import op

revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

TENANT_TABLES = [
    "organizations",
    "workspaces",
    "tenant_memberships",
    "teams",
    "team_members",
    "roles",
    "role_permissions",
    "user_roles",
    "config_overlays",
    "data_sources",
    "documents",
    "document_versions",
    "document_chunks",
    "embedding_profiles",
    "chunk_embeddings",
    "ingestion_jobs",
    "conversations",
    "messages",
    "message_citations",
    "retrieval_events",
    "user_memories",
    "message_feedback",
    "audit_logs",
    "usage_events",
    "evaluation_datasets",
    "evaluation_items",
    "evaluation_runs",
    "evaluation_results",
]

PERMISSIONS = [
    ("document:read", "Read documents and retrieved chunks"),
    ("document:write", "Upload or update documents"),
    ("document:delete", "Delete documents"),
    ("conversation:read", "Read conversations"),
    ("conversation:write", "Create messages"),
    ("conversation:delete", "Delete conversations"),
    ("source:manage", "Connect and sync data sources"),
    ("user:manage", "Manage users, teams, and roles"),
    ("config:read", "Read effective configuration"),
    ("config:write", "Update tenant/workspace configuration"),
    ("job:read", "View ingestion jobs"),
    ("audit:read", "Read audit logs"),
    ("workspace:manage", "Manage workspaces"),
    ("team:manage", "Manage teams"),
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE SCHEMA IF NOT EXISTS app_security")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_security.current_tenant_id()
        RETURNS uuid
        LANGUAGE sql
        STABLE
        AS $$
          SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid
        $$
        """
    )

    op.execute(
        """
        CREATE TABLE tenants (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(255) NOT NULL,
            slug VARCHAR(128) NOT NULL UNIQUE,
            residency VARCHAR(64),
            status VARCHAR(32) NOT NULL DEFAULT 'active',
            privacy JSONB NOT NULL DEFAULT '{}'::jsonb,
            budget JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE organizations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            name VARCHAR(255) NOT NULL,
            slug VARCHAR(128) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, slug)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE workspaces (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            organization_id UUID NOT NULL REFERENCES organizations(id),
            name VARCHAR(255) NOT NULL,
            slug VARCHAR(128) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, organization_id, slug)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email CITEXT NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE tenant_memberships (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            user_id UUID NOT NULL REFERENCES users(id),
            default_workspace_id UUID REFERENCES workspaces(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, user_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE teams (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            workspace_id UUID REFERENCES workspaces(id),
            name VARCHAR(255) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE team_members (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            team_id UUID NOT NULL REFERENCES teams(id),
            user_id UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (team_id, user_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE permissions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code VARCHAR(128) NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT ''
        )
        """
    )
    op.execute(
        """
        CREATE TABLE roles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            name VARCHAR(128) NOT NULL,
            is_system BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE role_permissions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            role_id UUID NOT NULL REFERENCES roles(id),
            permission_id UUID NOT NULL REFERENCES permissions(id),
            UNIQUE (role_id, permission_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE user_roles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            user_id UUID NOT NULL REFERENCES users(id),
            role_id UUID NOT NULL REFERENCES roles(id),
            workspace_id UUID REFERENCES workspaces(id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE config_overlays (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            scope_type VARCHAR(32) NOT NULL,
            scope_id UUID NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, scope_type, scope_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE data_sources (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            workspace_id UUID NOT NULL REFERENCES workspaces(id),
            name VARCHAR(255) NOT NULL,
            connector_type VARCHAR(64) NOT NULL,
            connector_config JSONB NOT NULL DEFAULT '{}'::jsonb,
            cursor JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(32) NOT NULL DEFAULT 'disconnected',
            last_synced_at TIMESTAMPTZ,
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE documents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            workspace_id UUID NOT NULL REFERENCES workspaces(id),
            source_id UUID NOT NULL REFERENCES data_sources(id),
            source_file_id VARCHAR(512) NOT NULL,
            path TEXT NOT NULL,
            title VARCHAR(512),
            classification VARCHAR(64) NOT NULL DEFAULT 'internal',
            acl JSONB NOT NULL DEFAULT '{}'::jsonb,
            active_version_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE document_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            document_id UUID NOT NULL REFERENCES documents(id),
            version_number INTEGER NOT NULL,
            checksum VARCHAR(128),
            content_hash VARCHAR(128) NOT NULL,
            etag VARCHAR(255),
            revision VARCHAR(255),
            mime_type VARCHAR(255) NOT NULL,
            storage_key TEXT NOT NULL,
            size_bytes BIGINT,
            parser_provider VARCHAR(64),
            parser_version VARCHAR(64),
            chunker_strategy VARCHAR(64),
            chunker_version VARCHAR(64),
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            source_created_at TIMESTAMPTZ,
            source_modified_at TIMESTAMPTZ,
            ingested_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (document_id, version_number)
        )
        """
    )
    op.execute(
        """
        ALTER TABLE documents
            ADD CONSTRAINT fk_documents_active_version_id
            FOREIGN KEY (active_version_id) REFERENCES document_versions(id)
        """
    )
    op.execute(
        """
        CREATE TABLE document_chunks (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            document_id UUID NOT NULL REFERENCES documents(id),
            version_id UUID NOT NULL REFERENCES document_versions(id),
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            page INTEGER,
            section VARCHAR(512),
            token_count INTEGER,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            search_vector TSVECTOR GENERATED ALWAYS AS (
                to_tsvector('english', coalesce(text, ''))
            ) STORED,
            UNIQUE (version_id, chunk_index)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_document_chunks_search_vector ON document_chunks USING GIN (search_vector)"
    )
    op.execute(
        """
        CREATE TABLE embedding_profiles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            provider VARCHAR(64) NOT NULL,
            model VARCHAR(255) NOT NULL,
            dimensions INTEGER NOT NULL,
            version VARCHAR(64) NOT NULL DEFAULT '1',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, provider, model, dimensions, version)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE chunk_embeddings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            chunk_id UUID NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
            embedding_profile_id UUID NOT NULL REFERENCES embedding_profiles(id),
            embedding vector,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (chunk_id, embedding_profile_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE ingestion_jobs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            job_type VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'queued',
            progress JSONB NOT NULL DEFAULT '{}'::jsonb,
            attempts INTEGER NOT NULL DEFAULT 0,
            idempotency_key VARCHAR(512) NOT NULL,
            error TEXT,
            document_id UUID REFERENCES documents(id),
            version_id UUID REFERENCES document_versions(id),
            source_id UUID REFERENCES data_sources(id),
            queue_message_id VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, idempotency_key),
            CONSTRAINT ck_ingestion_jobs_status CHECK (
                status IN (
                    'queued','processing','parsing','chunking','embedding',
                    'indexing','completed','failed','dead_letter','cancelled'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE conversations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            workspace_id UUID NOT NULL REFERENCES workspaces(id),
            user_id UUID NOT NULL REFERENCES users(id),
            title VARCHAR(512),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            conversation_id UUID NOT NULL REFERENCES conversations(id),
            role VARCHAR(32) NOT NULL,
            content TEXT NOT NULL,
            model VARCHAR(255),
            config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            token_usage JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE message_citations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            message_id UUID NOT NULL REFERENCES messages(id),
            document_id UUID NOT NULL REFERENCES documents(id),
            version_id UUID NOT NULL REFERENCES document_versions(id),
            chunk_id UUID NOT NULL REFERENCES document_chunks(id),
            page INTEGER,
            section VARCHAR(512),
            document_name VARCHAR(512),
            score DOUBLE PRECISION
        )
        """
    )
    op.execute(
        """
        CREATE TABLE retrieval_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            message_id UUID NOT NULL REFERENCES messages(id),
            query TEXT NOT NULL,
            retriever VARCHAR(64),
            reranker VARCHAR(64),
            llm VARCHAR(255),
            embedding_model VARCHAR(255),
            chunks JSONB NOT NULL DEFAULT '{}'::jsonb,
            latency_ms INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE user_memories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            user_id UUID NOT NULL REFERENCES users(id),
            content TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE message_feedback (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            message_id UUID NOT NULL REFERENCES messages(id),
            user_id UUID NOT NULL REFERENCES users(id),
            rating VARCHAR(32) NOT NULL,
            reason TEXT,
            expected_source TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE audit_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            actor_user_id UUID REFERENCES users(id),
            action VARCHAR(128) NOT NULL,
            resource_type VARCHAR(64) NOT NULL,
            resource_id UUID,
            request_id VARCHAR(64),
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE usage_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            user_id UUID REFERENCES users(id),
            event_type VARCHAR(64) NOT NULL,
            provider VARCHAR(64),
            model VARCHAR(255),
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            estimated_cost_usd DOUBLE PRECISION,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE evaluation_datasets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            name VARCHAR(255) NOT NULL,
            description TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE evaluation_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            dataset_id UUID NOT NULL REFERENCES evaluation_datasets(id),
            question TEXT NOT NULL,
            expected_answer TEXT,
            expected_sources JSONB NOT NULL DEFAULT '[]'::jsonb
        )
        """
    )
    op.execute(
        """
        CREATE TABLE evaluation_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            dataset_id UUID NOT NULL REFERENCES evaluation_datasets(id),
            config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE evaluation_results (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            run_id UUID NOT NULL REFERENCES evaluation_runs(id),
            item_id UUID NOT NULL REFERENCES evaluation_items(id),
            metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
            actual_answer TEXT,
            actual_sources JSONB NOT NULL DEFAULT '[]'::jsonb
        )
        """
    )

    op.execute("CREATE INDEX ix_documents_tenant_workspace ON documents (tenant_id, workspace_id)")
    op.execute("CREATE INDEX ix_ingestion_jobs_tenant_status ON ingestion_jobs (tenant_id, status)")
    op.execute("CREATE INDEX ix_audit_logs_tenant_created ON audit_logs (tenant_id, created_at)")
    op.execute("CREATE INDEX ix_messages_conversation_created ON messages (conversation_id, created_at)")
    op.execute("CREATE INDEX ix_data_sources_workspace ON data_sources (tenant_id, workspace_id)")

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

    for code, description in PERMISSIONS:
        op.execute(
            "INSERT INTO permissions (code, description) VALUES "
            f"({_sql_str(code)}, {_sql_str(description)})"
        )


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def downgrade() -> None:
    for table in reversed(
        [
            "evaluation_results",
            "evaluation_runs",
            "evaluation_items",
            "evaluation_datasets",
            "usage_events",
            "audit_logs",
            "message_feedback",
            "user_memories",
            "retrieval_events",
            "message_citations",
            "messages",
            "conversations",
            "ingestion_jobs",
            "chunk_embeddings",
            "embedding_profiles",
            "document_chunks",
            "document_versions",
            "documents",
            "data_sources",
            "config_overlays",
            "user_roles",
            "role_permissions",
            "roles",
            "permissions",
            "team_members",
            "teams",
            "tenant_memberships",
            "users",
            "workspaces",
            "organizations",
            "tenants",
        ]
    ):
        if table in TENANT_TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP FUNCTION IF EXISTS app_security.current_tenant_id()")
    op.execute("DROP SCHEMA IF EXISTS app_security CASCADE")
