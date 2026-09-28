"""Content-addressed blobs and derived indexes.

Revision ID: 004_content_address
Revises: 003_connectors
Create Date: 2026-09-23
"""

from __future__ import annotations

from alembic import op

revision = "004_content_address"
down_revision = "003_connectors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE content_objects (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            content_hash VARCHAR(128) NOT NULL,
            storage_key TEXT NOT NULL,
            mime_type VARCHAR(255) NOT NULL,
            size_bytes BIGINT,
            ref_count INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, content_hash)
        )
        """
    )
    op.execute("CREATE INDEX ix_content_objects_tenant_id ON content_objects (tenant_id)")
    op.execute("ALTER TABLE content_objects ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE content_objects FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON content_objects
        USING (tenant_id = app_security.current_tenant_id())
        WITH CHECK (tenant_id = app_security.current_tenant_id())
        """
    )
    op.execute("ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS content_object_id UUID REFERENCES content_objects(id)")
    op.execute("ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS derived_from_version_id UUID REFERENCES document_versions(id)")
    op.execute("ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS pipeline_fingerprint VARCHAR(64)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_versions_content_hash ON document_versions (tenant_id, content_hash, pipeline_fingerprint, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_versions_derived_from ON document_versions (derived_from_version_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_versions_derived_from")
    op.execute("DROP INDEX IF EXISTS ix_document_versions_content_hash")
    op.execute("ALTER TABLE document_versions DROP COLUMN IF EXISTS pipeline_fingerprint")
    op.execute("ALTER TABLE document_versions DROP COLUMN IF EXISTS derived_from_version_id")
    op.execute("ALTER TABLE document_versions DROP COLUMN IF EXISTS content_object_id")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON content_objects")
    op.execute("DROP TABLE IF EXISTS content_objects")
