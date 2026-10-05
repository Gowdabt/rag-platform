"""Revoke Tenant Admin document:read_all; tenant-wide ACL for admin-owned uploads.

Revision ID: 009_document_visibility_defaults
Revises: 008_authz_epoch
Create Date: 2026-09-30
"""

from __future__ import annotations

from alembic import op

revision = "009_document_visibility_defaults"
down_revision = "008_authz_epoch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tenant Admin must follow document ACLs; private member uploads stay private unless granted.
    op.execute(
        """
        DELETE FROM role_permissions rp
        USING roles r, permissions p
        WHERE rp.role_id = r.id
          AND rp.permission_id = p.id
          AND r.name IN ('Tenant Admin', 'Admin')
          AND p.code = 'document:read_all'
        """
    )
    # Existing Tenant Admin uploads were private-only; open them to the tenant by default.
    op.execute(
        """
        UPDATE documents d
        SET acl = jsonb_set(COALESCE(d.acl, '{}'::jsonb), '{visibility}', '"tenant"', true)
        WHERE d.owner_user_id IS NOT NULL
          AND COALESCE(d.acl->>'visibility', 'private') = 'private'
          AND EXISTS (
            SELECT 1
            FROM user_roles ur
            JOIN roles r ON r.id = ur.role_id AND r.tenant_id = ur.tenant_id
            WHERE ur.user_id = d.owner_user_id
              AND ur.tenant_id = d.tenant_id
              AND r.name IN ('Tenant Admin', 'Admin')
          )
        """
    )
    op.execute("UPDATE tenants SET authz_epoch = authz_epoch + 1")


def downgrade() -> None:
    op.execute(
        """
        INSERT INTO role_permissions (tenant_id, role_id, permission_id)
        SELECT r.tenant_id, r.id, p.id
        FROM roles r
        JOIN permissions p ON p.code = 'document:read_all'
        WHERE r.name IN ('Tenant Admin', 'Admin')
          AND NOT EXISTS (
            SELECT 1 FROM role_permissions rp
            WHERE rp.role_id = r.id AND rp.permission_id = p.id
          )
        """
    )
    op.execute("UPDATE tenants SET authz_epoch = authz_epoch + 1")
