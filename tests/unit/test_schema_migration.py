from pathlib import Path


def test_initial_migration_enforces_rls_and_versions():
    root = Path(__file__).resolve().parents[2]
    migration = root / "backend/alembic/versions/001_initial_schema.py"
    text = migration.read_text(encoding="utf-8")
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "FORCE ROW LEVEL SECURITY" in text
    assert "document_versions" in text
    assert "ingestion_jobs" in text
    assert "audit_logs" in text
    assert "embedding_profiles" in text
    assert "search_vector" in text


def test_owner_acl_migration_adds_owners_and_does_not_drop_rls():
    root = Path(__file__).resolve().parents[2]
    migration = root / "backend/alembic/versions/006_owner_acl.py"
    text = migration.read_text(encoding="utf-8")
    upgrade, _, _downgrade = text.partition("def downgrade")
    assert "owner_user_id" in upgrade
    assert "source:admin" in upgrade
    assert "document:read_all" in upgrade
    assert "DROP POLICY" not in upgrade
    assert "DISABLE ROW LEVEL SECURITY" not in upgrade


def test_saas_platform_migration_adds_invitations_folders_and_rls():
    root = Path(__file__).resolve().parents[2]
    migration = root / "backend/alembic/versions/007_saas_platform.py"
    text = migration.read_text(encoding="utf-8")
    upgrade, _, _downgrade = text.partition("def downgrade")
    assert 'down_revision = "006_owner_acl"' in text
    assert "is_super_admin" in upgrade
    assert "invitations" in upgrade
    assert "folders" in upgrade
    assert "resource_permissions" in upgrade
    assert "ENABLE ROW LEVEL SECURITY" in upgrade
    assert "FORCE ROW LEVEL SECURITY" in upgrade
    assert "Tenant Admin" in upgrade
    assert "users.view" in upgrade
    assert "DISABLE ROW LEVEL SECURITY" not in upgrade


def test_authz_epoch_migration_persists_cross_worker_version():
    root = Path(__file__).resolve().parents[2]
    migration = root / "backend/alembic/versions/008_authz_epoch.py"
    text = migration.read_text(encoding="utf-8")
    upgrade, _, _downgrade = text.partition("def downgrade")
    assert 'down_revision = "007_saas_platform"' in text
    assert "authz_epoch" in upgrade
    assert "rate_limit_buckets" in upgrade
    assert "tenants ADD COLUMN" in upgrade
    assert "users ADD COLUMN" in upgrade


def test_content_address_migration_is_tenant_scoped():
    root = Path(__file__).resolve().parents[2]
    migration = root / "backend/alembic/versions/004_content_address.py"
    text = migration.read_text(encoding="utf-8")
    assert "UNIQUE (tenant_id, content_hash)" in text
    assert "derived_from_version_id" in text
    assert "pipeline_fingerprint" in text
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "FORCE ROW LEVEL SECURITY" in text


def test_connector_migration_enforces_rls_and_external_identity():
    root = Path(__file__).resolve().parents[2]
    migration = root / "backend/alembic/versions/003_connectors.py"
    text = migration.read_text(encoding="utf-8")
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "source_subscriptions" in text
    assert "connector_credentials" in text
    assert "sync_runs" in text
    assert "encrypted_access_token" in text
    assert "uq_documents_source_file" in text
