"""SaaS platform: super admin, invitations, folders, resource grants.

Revision ID: 007_saas_platform
Revises: 006_owner_acl
Create Date: 2026-09-28
"""

from __future__ import annotations

import os

from alembic import op

revision = "007_saas_platform"
down_revision = "006_owner_acl"
branch_labels = None
depends_on = None

NEW_PERMISSIONS = [
    ("users.view", "View tenant users"),
    ("users.create", "Invite tenant users"),
    ("users.update", "Update tenant users"),
    ("users.disable", "Disable or enable tenant users"),
    ("roles.view", "View roles"),
    ("roles.create", "Create roles"),
    ("roles.update", "Update roles"),
    ("roles.delete", "Delete roles"),
    ("roles.assign", "Assign roles to users"),
    ("folders.view", "View all folders in the tenant"),
    ("folders.create", "Create folders"),
    ("folders.update", "Update folders"),
    ("folders.delete", "Delete folders"),
    ("folders.share", "Share folders"),
    ("documents.view", "View documents"),
    ("documents.upload", "Upload documents"),
    ("documents.update", "Update documents"),
    ("documents.delete", "Delete documents"),
    ("documents.share", "Share documents"),
    ("ai.chat", "Use AI chat"),
    ("ai.configuration.view", "View tenant AI configuration"),
    ("ai.configuration.update", "Update tenant AI configuration"),
    ("audit.view", "View audit logs"),
    ("tenant.settings.view", "View tenant settings"),
    ("tenant.settings.update", "Update tenant settings"),
]

# Old code -> new codes copied onto existing roles that already have the old code.
PERM_MAP = [
    ("document:read", "documents.view"),
    ("document:write", "documents.upload"),
    ("document:write", "documents.update"),
    ("document:write", "documents.share"),
    ("document:write", "folders.create"),
    ("document:write", "folders.share"),
    ("document:delete", "documents.delete"),
    ("document:delete", "folders.delete"),
    ("user:manage", "users.view"),
    ("user:manage", "users.create"),
    ("user:manage", "users.update"),
    ("user:manage", "users.disable"),
    ("user:manage", "roles.view"),
    ("user:manage", "roles.create"),
    ("user:manage", "roles.update"),
    ("user:manage", "roles.delete"),
    ("user:manage", "roles.assign"),
    ("config:read", "tenant.settings.view"),
    ("config:read", "ai.configuration.view"),
    ("config:write", "tenant.settings.update"),
    ("config:write", "ai.configuration.update"),
    ("audit:read", "audit.view"),
    ("conversation:write", "ai.chat"),
]


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _enable_rls(table: str) -> None:
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


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_super_admin BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name TEXT")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ")
    op.execute("ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL")
    op.execute("ALTER TABLE roles ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE refresh_tokens ALTER COLUMN tenant_id DROP NOT NULL")
    op.execute("ALTER TABLE audit_logs ALTER COLUMN tenant_id DROP NOT NULL")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON audit_logs")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON audit_logs
        USING (tenant_id IS NOT DISTINCT FROM app_security.current_tenant_id())
        WITH CHECK (tenant_id IS NOT DISTINCT FROM app_security.current_tenant_id())
        """
    )

    op.execute(
        """
        CREATE TABLE invitations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            email CITEXT NOT NULL,
            name TEXT,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            purpose VARCHAR(32) NOT NULL DEFAULT 'invite',
            expires_at TIMESTAMPTZ NOT NULL,
            accepted_at TIMESTAMPTZ,
            invited_by UUID REFERENCES users(id),
            role_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            invited_user_id UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT invitations_purpose_check CHECK (purpose IN ('invite', 'reset'))
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_invitations_tenant_email ON invitations (tenant_id, email)")

    op.execute(
        """
        CREATE TABLE folders (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            workspace_id UUID NOT NULL REFERENCES workspaces(id),
            parent_id UUID REFERENCES folders(id),
            name VARCHAR(255) NOT NULL,
            owner_user_id UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_folders_workspace ON folders (tenant_id, workspace_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_folders_parent ON folders (tenant_id, parent_id)")
    _enable_rls("folders")

    op.execute(
        """
        CREATE TABLE resource_permissions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            resource_type VARCHAR(64) NOT NULL,
            resource_id UUID NOT NULL,
            subject_type VARCHAR(32) NOT NULL,
            subject_id UUID NOT NULL,
            actions JSONB NOT NULL DEFAULT '[]'::jsonb,
            deny BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, resource_type, resource_id, subject_type, subject_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_resource_permissions_resource "
        "ON resource_permissions (tenant_id, resource_type, resource_id)"
    )
    _enable_rls("resource_permissions")

    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS folder_id UUID REFERENCES folders(id)")
    op.execute("ALTER TABLE source_subscriptions ADD COLUMN IF NOT EXISTS folder_id UUID REFERENCES folders(id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_folder ON documents (tenant_id, folder_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_source_subscriptions_folder "
        "ON source_subscriptions (tenant_id, folder_id)"
    )

    for code, description in NEW_PERMISSIONS:
        op.execute(
            "INSERT INTO permissions (code, description) "
            f"SELECT {_sql_str(code)}, {_sql_str(description)} "
            f"WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = {_sql_str(code)})"
        )

    for old, new in PERM_MAP:
        op.execute(
            f"""
            INSERT INTO role_permissions (tenant_id, role_id, permission_id)
            SELECT rp.tenant_id, rp.role_id, p_new.id
            FROM role_permissions rp
            JOIN permissions p_old ON p_old.id = rp.permission_id AND p_old.code = {_sql_str(old)}
            JOIN permissions p_new ON p_new.code = {_sql_str(new)}
            WHERE NOT EXISTS (
                SELECT 1 FROM role_permissions existing
                WHERE existing.role_id = rp.role_id AND existing.permission_id = p_new.id
            )
            """
        )

    # Tenant Admin / remaining Admin system roles get every new permission.
    new_codes_sql = ", ".join(_sql_str(code) for code, _ in NEW_PERMISSIONS)
    op.execute(
        f"""
        INSERT INTO role_permissions (tenant_id, role_id, permission_id)
        SELECT r.tenant_id, r.id, p.id
        FROM roles r
        JOIN permissions p ON p.code IN ({new_codes_sql})
        WHERE r.is_system = true
          AND r.name IN ('Admin', 'Tenant Admin')
          AND NOT EXISTS (
            SELECT 1 FROM role_permissions rp
            WHERE rp.role_id = r.id AND rp.permission_id = p.id
          )
        """
    )
    old_admin_codes = (
        "document:read",
        "document:read_all",
        "document:write",
        "document:delete",
        "conversation:read",
        "conversation:write",
        "conversation:delete",
        "source:manage",
        "source:admin",
        "user:manage",
        "config:read",
        "config:write",
        "job:read",
        "audit:read",
        "workspace:manage",
        "team:manage",
    )
    old_codes_sql = ", ".join(_sql_str(code) for code in old_admin_codes)
    op.execute(
        f"""
        INSERT INTO role_permissions (tenant_id, role_id, permission_id)
        SELECT r.tenant_id, r.id, p.id
        FROM roles r
        JOIN permissions p ON p.code IN ({old_codes_sql})
        WHERE r.is_system = true
          AND r.name IN ('Admin', 'Tenant Admin')
          AND NOT EXISTS (
            SELECT 1 FROM role_permissions rp
            WHERE rp.role_id = r.id AND rp.permission_id = p.id
          )
        """
    )

    op.execute(
        """
        UPDATE roles AS r
        SET name = 'Tenant Admin'
        WHERE r.name = 'Admin' AND r.is_system = true
          AND NOT EXISTS (
            SELECT 1 FROM roles other
            WHERE other.tenant_id = r.tenant_id AND other.name = 'Tenant Admin'
          )
        """
    )

    op.execute(
        """
        DO $$
        DECLARE
          r RECORD;
          fid UUID;
        BEGIN
          FOR r IN
            SELECT ss.id, ss.tenant_id, ss.workspace_id, ss.external_location_name, ds.owner_user_id
            FROM source_subscriptions ss
            JOIN data_sources ds ON ds.id = ss.source_id
            WHERE ss.folder_id IS NULL
          LOOP
            INSERT INTO folders (tenant_id, workspace_id, name, owner_user_id)
            VALUES (r.tenant_id, r.workspace_id, r.external_location_name, r.owner_user_id)
            RETURNING id INTO fid;
            UPDATE source_subscriptions SET folder_id = fid WHERE id = r.id;
          END LOOP;
        END $$
        """
    )
    op.execute(
        """
        UPDATE documents d
        SET folder_id = s.folder_id
        FROM source_subscriptions s
        WHERE d.subscription_id = s.id
          AND d.folder_id IS NULL
          AND s.folder_id IS NOT NULL
        """
    )

    email = os.environ.get("PLATFORM_SUPERADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("PLATFORM_SUPERADMIN_PASSWORD", "")
    if email and password:
        from app.core.security import hash_password

        hashed = hash_password(password).replace("'", "''")
        email_sql = email.replace("'", "''")
        op.execute(
            f"""
            INSERT INTO users (email, password_hash, status, is_super_admin, display_name)
            SELECT '{email_sql}', '{hashed}', 'active', true, 'Platform Super Admin'
            WHERE NOT EXISTS (SELECT 1 FROM users WHERE email = '{email_sql}')
            """
        )
        op.execute(
            f"""
            UPDATE users
            SET is_super_admin = true, password_hash = '{hashed}', status = 'active'
            WHERE email = '{email_sql}'
            """
        )


def downgrade() -> None:
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS folder_id")
    op.execute("ALTER TABLE source_subscriptions DROP COLUMN IF EXISTS folder_id")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON resource_permissions")
    op.execute("DROP TABLE IF EXISTS resource_permissions")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON folders")
    op.execute("DROP TABLE IF EXISTS folders")
    op.execute("DROP TABLE IF EXISTS invitations")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON audit_logs")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON audit_logs
        USING (tenant_id = app_security.current_tenant_id())
        WITH CHECK (tenant_id = app_security.current_tenant_id())
        """
    )
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permissions WHERE code IN ({codes})
        )
        """.format(codes=", ".join(_sql_str(code) for code, _ in NEW_PERMISSIONS))
    )
    op.execute(
        "DELETE FROM permissions WHERE code IN ({codes})".format(
            codes=", ".join(_sql_str(code) for code, _ in NEW_PERMISSIONS)
        )
    )
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_login_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS display_name")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_super_admin")
    op.execute("ALTER TABLE roles DROP COLUMN IF EXISTS description")
