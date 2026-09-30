from pathlib import Path


def test_frontend_does_not_store_provider_secrets_and_logout_clears_tokens():
    root = Path(__file__).resolve().parents[2]
    client = (root / "frontend/src/api/client.ts").read_text(encoding="utf-8")
    app = (root / "frontend/src/App.tsx").read_text(encoding="utf-8")
    assert "localStorage.setItem(\"access_token\"" in app or "localStorage.setItem('access_token'" in app
    assert "removeItem(\"access_token\")" in app or "removeItem('access_token')" in app
    assert "removeItem(\"refresh_token\")" in app or "removeItem('refresh_token')" in app
    assert "/api/v1/auth/logout" in client
    assert "JWT_SECRET" not in client
    assert "OPENAI_API_KEY" not in client
    assert "JWT_SECRET" not in app
    assert "OPENAI_API_KEY" not in app
    # OAuth API payloads may include a client_secret field name; it must not land in UI state.
    assert "localStorage" in app
    assert "client_secret" not in app
    chat = (root / "frontend/src/pages/ChatPage.tsx").read_text(encoding="utf-8")
    docs = (root / "frontend/src/pages/DocumentsPage.tsx").read_text(encoding="utf-8")
    folders = (root / "frontend/src/pages/FoldersPage.tsx").read_text(encoding="utf-8")
    untrusted = (root / "frontend/src/security/untrusted.ts").read_text(encoding="utf-8")
    for source in (chat, docs, folders, app, client):
        assert "dangerouslySetInnerHTML" not in source
        assert ".innerHTML" not in source
    assert "untrustedText" in chat
    assert "untrustedText" in docs
    assert "untrustedText" in folders
    assert "replace(/<[^>]*>/g" in untrusted or "replace(/<[^>]*>/g, \"\")" in untrusted


def test_forgot_password_does_not_surface_reset_token():
    root = Path(__file__).resolve().parents[2]
    forgot = (root / "frontend/src/pages/ForgotPasswordPage.tsx").read_text(encoding="utf-8")
    reset = (root / "frontend/src/pages/ResetPasswordPage.tsx").read_text(encoding="utf-8")
    client = (root / "frontend/src/api/client.ts").read_text(encoding="utf-8")
    app = (root / "frontend/src/App.tsx").read_text(encoding="utf-8")
    identity = (root / "backend/app/application/identity.py").read_text(encoding="utf-8")
    assert "continue-to-reset" not in forgot
    assert "reset_token" not in forgot
    assert "resetToken" not in forgot
    assert "password reset link has been sent" in forgot
    assert 'payload["reset_token"]' not in identity
    assert "params.get(\"token\")" in reset
    assert "params.get(\"slug\")" in reset
    assert "Password must be at least 10 characters" in reset
    assert "trim().toLowerCase()" in client
    assert "tenantSlug.trim().toLowerCase()" in app


def test_frontend_tables_do_not_use_tailwind_table_row_utility():
    root = Path(__file__).resolve().parents[2] / "frontend" / "src"
    css = (root / "index.css").read_text(encoding="utf-8")
    assert ".table-row" not in css
    assert ".data-row" in css
    assert ".cols-tenant" in css
    offenders = [path.name for path in root.rglob("*.tsx") if "table-row" in path.read_text(encoding="utf-8")]
    assert offenders == [], f"class table-row collides with Tailwind display:table-row: {offenders}"
    tenants = (root / "pages" / "TenantsPage.tsx").read_text(encoding="utf-8")
    assert "cols-tenant" in tenants
    assert "tenant-invite-panel" in tenants
    assert "Temporary admin password" in tenants
    assert "No default password" in tenants or "does not create a default password" in tenants
    assert "starter accounts" in tenants
    assert "seeded-users" in tenants
    assert "seeded-user-" in tenants


def test_frontend_authz_contracts_match_api():
    root = Path(__file__).resolve().parents[2] / "frontend" / "src"
    app = (root / "App.tsx").read_text(encoding="utf-8")
    access = (root / "auth" / "access.ts").read_text(encoding="utf-8")
    client = (root / "api" / "client.ts").read_text(encoding="utf-8")
    roles = (root / "pages" / "RolesPage.tsx").read_text(encoding="utf-8")
    folders = (root / "pages" / "FoldersPage.tsx").read_text(encoding="utf-8")
    users = (root / "pages" / "UsersPage.tsx").read_text(encoding="utf-8")
    assert "isSuperAdmin(user) || hasAnyPermission" not in app
    assert "function PermRoute" in app
    assert "isSuperAdmin(user)" in app
    assert "expandPermissions" in access
    assert '"user:manage"' in access
    assert "subject_type" in client
    assert "role_names: body.role_names || body.roles" in client
    assert "permission_codes || role.permissions" in roles
    assert "subject_type: shareType" in folders
    assert "role_names: roleNames" in users
    assert "users.create" in users
    assert "Copy invite" in users
    assert "resend-invite" in client
    assert "Edit user" in users
    assert ">Actions</span>" in users


def test_frontend_data_tables_use_fixed_grid_tracks():
    import re

    root = Path(__file__).resolve().parents[2] / "frontend" / "src"
    css = (root / "index.css").read_text(encoding="utf-8")
    assert ".table-row" not in css
    assert "auto auto auto" not in css

    def tracks(class_name: str) -> int:
        match = re.search(
            rf"\.{re.escape(class_name)}\s*\{{[^}}]*grid-template-columns:\s*([^;]+);",
            css,
        )
        assert match, class_name
        collapsed = re.sub(r"minmax\([^)]+\)", "X", match.group(1))
        return len(collapsed.split())

    assert tracks("cols-tenant") == 5
    assert tracks("cols-3") == 3
    assert tracks("cols-4") == 4
    assert tracks("cols-5") == 5
    assert tracks("cols-6") == 6
    assert tracks("cols-audit-3") == 3
    assert tracks("cols-audit-4") == 4

    users = (root / "pages" / "UsersPage.tsx").read_text(encoding="utf-8")
    assert "data-head cols-6" in users
    assert "<span>Last login</span>" in users
    assert "<span>Actions</span>" in users
    assert "data-testid=\"user-actions\"" in users
    assert "data-testid=\"user-last-login\"" in users
    assert "data-testid=\"user-status\"" in users
    assert "formatWhen(user.last_login_at)" in users
    roles = (root / "pages" / "RolesPage.tsx").read_text(encoding="utf-8")
    assert "<span>Actions</span>" in roles
    tenants = (root / "pages" / "TenantsPage.tsx").read_text(encoding="utf-8")
    assert "<span>Actions</span>" in tenants
    docs = (root / "pages" / "DocumentsPage.tsx").read_text(encoding="utf-8")
    assert "data-head cols-5" in docs
    assert "data-row cols-5" in docs
