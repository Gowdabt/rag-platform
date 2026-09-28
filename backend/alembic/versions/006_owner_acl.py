"""Document/source owners, intra-tenant ACL, and Admin-only permissions.

Revision ID: 006_owner_acl
Revises: 005_oauth_state_source
Create Date: 2026-09-28
"""

from __future__ import annotations

from alembic import op

revision = "006_owner_acl"
down_revision = "005_oauth_state_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES users(id)")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES users(id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_data_sources_owner ON data_sources (tenant_id, owner_user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_owner ON documents (tenant_id, owner_user_id)")

    op.execute(
        """
        INSERT INTO permissions (code, description)
        SELECT 'source:admin', 'Administer all connectors in the tenant'
        WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'source:admin')
        """
    )
    op.execute(
        """
        INSERT INTO permissions (code, description)
        SELECT 'document:read_all', 'Read all documents in the tenant regardless of ACL'
        WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'document:read_all')
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (tenant_id, role_id, permission_id)
        SELECT r.tenant_id, r.id, p.id
        FROM roles r
        JOIN permissions p ON p.code IN ('source:admin', 'document:read_all')
        WHERE r.name = 'Admin' AND r.is_system = true
          AND NOT EXISTS (
            SELECT 1 FROM role_permissions rp
            WHERE rp.role_id = r.id AND rp.permission_id = p.id
          )
        """
    )

    op.execute(
        """
        UPDATE data_sources ds
        SET owner_user_id = (
            SELECT os.user_id
            FROM oauth_states os
            WHERE os.source_id = ds.id
            ORDER BY os.created_at DESC
            LIMIT 1
        )
        WHERE owner_user_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE data_sources ds
        SET owner_user_id = (
            SELECT tm.user_id
            FROM tenant_memberships tm
            WHERE tm.tenant_id = ds.tenant_id
            ORDER BY tm.created_at ASC
            LIMIT 1
        )
        WHERE owner_user_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE documents d
        SET owner_user_id = ds.owner_user_id
        FROM data_sources ds
        WHERE d.source_id = ds.id
          AND d.owner_user_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE documents
        SET acl = jsonb_build_object(
            'owner_id', owner_user_id::text,
            'visibility', 'private',
            'allowed_users', jsonb_build_array(owner_user_id::text),
            'allowed_groups', '[]'::jsonb,
            'allowed_roles', '[]'::jsonb,
            'denied_users', '[]'::jsonb,
            'denied_groups', '[]'::jsonb,
            'denied_roles', '[]'::jsonb
        )
        WHERE owner_user_id IS NOT NULL
          AND (acl IS NULL OR acl = '{}'::jsonb)
        """
    )
    op.execute(
        """
        UPDATE source_subscriptions sub
        SET acl = jsonb_build_object(
            'owner_id', ds.owner_user_id::text,
            'visibility', 'private',
            'allowed_users', jsonb_build_array(ds.owner_user_id::text),
            'allowed_groups', '[]'::jsonb,
            'allowed_roles', '[]'::jsonb,
            'denied_users', '[]'::jsonb,
            'denied_groups', '[]'::jsonb,
            'denied_roles', '[]'::jsonb
        )
        FROM data_sources ds
        WHERE sub.source_id = ds.id
          AND ds.owner_user_id IS NOT NULL
          AND (sub.acl IS NULL OR sub.acl = '{}'::jsonb)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permissions WHERE code IN ('source:admin', 'document:read_all')
        )
        """
    )
    op.execute("DELETE FROM permissions WHERE code IN ('source:admin', 'document:read_all')")
    op.execute("DROP INDEX IF EXISTS ix_documents_owner")
    op.execute("DROP INDEX IF EXISTS ix_data_sources_owner")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS owner_user_id")
    op.execute("ALTER TABLE data_sources DROP COLUMN IF EXISTS owner_user_id")
