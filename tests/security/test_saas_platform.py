from __future__ import annotations

import os
from uuid import uuid4

import pytest
from app.core.security import hash_token
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text


def _signup(client: TestClient, *, prefix: str):
    email = f"{prefix}-{uuid4().hex[:8]}@example.com"
    signup = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "supersecret1", "tenant_name": f"{prefix}{uuid4().hex[:6]}"},
    )
    if signup.status_code >= 500:
        pytest.skip("database unavailable")
    assert signup.status_code == 200, signup.text
    body = signup.json()
    return email, {"Authorization": f"Bearer {body['access_token']}"}, body


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _expire_invite(raw_token: str) -> None:
    url = os.environ.get("DATABASE_URL_SYNC", "postgresql+psycopg://rag:rag@localhost:5432/rag")
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE invitations SET expires_at = NOW() - INTERVAL '1 day' WHERE token_hash = :h"),
                {"h": hash_token(raw_token)},
            )
    finally:
        engine.dispose()


def test_signup_forbidden_without_flag(monkeypatch):
    monkeypatch.delenv("RAG_ALLOW_PUBLIC_SIGNUP", raising=False)
    monkeypatch.setenv("RAG_ALLOW_PUBLIC_SIGNUP", "0")
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/signup",
            json={
                "email": f"blocked-{uuid4().hex[:8]}@example.com",
                "password": "supersecret1",
                "tenant_name": "Blocked Co",
            },
        )
        if response.status_code >= 500:
            pytest.skip("database unavailable")
        assert response.status_code == 403


def test_member_cannot_create_platform_tenant():
    app = create_app()
    with TestClient(app) as client:
        _admin_email, admin_headers, body = _signup(client, prefix="mem-block")
        member = f"member-{uuid4().hex[:8]}@example.com"
        invited = client.post(
            "/api/v1/users",
            headers=admin_headers,
            json={"email": member, "password": "supersecret1", "role": "Member"},
        )
        assert invited.status_code == 200, invited.text
        login = client.post(
            "/api/v1/auth/login",
            json={"email": member, "password": "supersecret1", "tenant_id": body["tenant_id"]},
        )
        assert login.status_code == 200, login.text
        response = client.post(
            "/api/v1/platform/tenants",
            headers=_headers(login.json()["access_token"]),
            json={
                "name": "Nope",
                "slug": f"nope-{uuid4().hex[:6]}",
                "admin_name": "Ada",
                "admin_email": f"ada-{uuid4().hex[:8]}@example.com",
            },
        )
        assert response.status_code == 403


def test_tenant_admin_cannot_create_platform_tenant():
    app = create_app()
    with TestClient(app) as client:
        _email, headers, _ = _signup(client, prefix="ta-block")
        response = client.post(
            "/api/v1/platform/tenants",
            headers=headers,
            json={
                "name": "Nope",
                "slug": f"nope-{uuid4().hex[:6]}",
                "admin_name": "Ada",
                "admin_email": f"ada-{uuid4().hex[:8]}@example.com",
            },
        )
        assert response.status_code == 403


def test_super_admin_creates_tenant_admin_accepts_invite_and_logs_in_with_slug(monkeypatch):
    sa_email = f"sa-{uuid4().hex[:8]}@example.com"
    monkeypatch.setenv("PLATFORM_SUPERADMIN_EMAIL", sa_email)
    monkeypatch.setenv("PLATFORM_SUPERADMIN_PASSWORD", "supersecret1")
    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": sa_email, "password": "supersecret1"})
        if login.status_code >= 500:
            pytest.skip("database unavailable")
        assert login.status_code == 200, login.text
        sa = _headers(login.json()["access_token"])
        me = client.get("/api/v1/auth/me", headers=sa)
        assert me.status_code == 200
        assert me.json()["is_super_admin"] is True
        assert me.json()["tenant_id"] is None

        slug = f"acme-{uuid4().hex[:6]}"
        admin_email = f"owner-{uuid4().hex[:8]}@example.com"
        created = client.post(
            "/api/v1/platform/tenants",
            headers=sa,
            json={
                "name": "Acme",
                "slug": slug,
                "admin_name": "Owner",
                "admin_email": admin_email,
                "status": "active",
            },
        )
        assert created.status_code == 200, created.text
        token = created.json()["invitation_token"]
        tenant = created.json()["tenant"]
        assert tenant["slug"] == slug
        listed = client.get("/api/v1/platform/tenants?limit=100&offset=0", headers=sa)
        assert listed.status_code == 200, listed.text
        match = next(row for row in listed.json() if row["slug"] == slug)
        assert match["name"] == "Acme"
        assert match.get("admin_email") == admin_email

        accepted = client.post(
            "/api/v1/auth/accept-invite",
            json={"token": token, "password": "supersecret1"},
        )
        assert accepted.status_code == 200, accepted.text

        logged = client.post(
            "/api/v1/auth/login",
            json={"email": admin_email, "password": "supersecret1", "tenant_slug": slug},
        )
        assert logged.status_code == 200, logged.text
        me_admin = client.get("/api/v1/auth/me", headers=_headers(logged.json()["access_token"]))
        assert me_admin.status_code == 200
        body = me_admin.json()
        assert body["is_super_admin"] is False
        assert body["tenant_slug"] == slug
        assert "Tenant Admin" in body["roles"] or "Admin" in body["roles"]


def test_super_admin_create_accepts_company_name_slugifies_and_optional_password(monkeypatch):
    sa_email = f"sa-{uuid4().hex[:8]}@example.com"
    monkeypatch.setenv("PLATFORM_SUPERADMIN_EMAIL", sa_email)
    monkeypatch.setenv("PLATFORM_SUPERADMIN_PASSWORD", "supersecret1")
    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": sa_email, "password": "supersecret1"})
        if login.status_code >= 500:
            pytest.skip("database unavailable")
        assert login.status_code == 200, login.text
        sa = _headers(login.json()["access_token"])
        suffix = uuid4().hex[:6]
        admin_email = f"gowda-{suffix}@salesforce.com"
        created = client.post(
            "/api/v1/platform/tenants",
            headers=sa,
            json={
                "company_name": "Salesforce",
                "slug": f"Salesforce-{suffix}",
                "admin_name": "Gowda",
                "admin_email": admin_email,
            },
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["slug"] == f"salesforce-{suffix}"
        assert body["tenant"]["name"] == "Salesforce"
        assert body["password_set"] is False
        assert body.get("invitation_token")
        assert body.get("invite_path", "").startswith("/invite?token=")
        assert body.get("invitation_expires_at")

        listed = client.get("/api/v1/platform/tenants?limit=100&offset=0", headers=sa)
        assert listed.status_code == 200
        row = next(item for item in listed.json() if item["slug"] == f"salesforce-{suffix}")
        assert row["admin_email"] == admin_email
        assert row["company_name"] == "Salesforce"

        missing = client.post(
            "/api/v1/platform/tenants",
            headers=sa,
            json={
                "company_name": "Nope",
                "slug": f"nope-{suffix}",
                "admin_name": "Ada",
            },
        )
        assert missing.status_code == 422
        assert "admin_email" in missing.json()["detail"]

        zero = client.get("/api/v1/platform/tenants?limit=0", headers=sa)
        assert zero.status_code == 422
        assert "limit" in zero.json()["detail"].lower()

        admin_email_pw = f"ready-{suffix}@salesforce.com"
        with_password = client.post(
            "/api/v1/platform/tenants",
            headers=sa,
            json={
                "name": "Ready Co",
                "slug": f"Ready-{suffix}",
                "admin_name": "Ready",
                "admin_email": admin_email_pw,
                "admin_password": "supersecret1",
            },
        )
        assert with_password.status_code == 200, with_password.text
        assert with_password.json()["password_set"] is True
        logged = client.post(
            "/api/v1/auth/login",
            json={"email": admin_email_pw, "password": "supersecret1", "tenant_slug": f"ready-{suffix}"},
        )
        assert logged.status_code == 200, logged.text


def test_super_admin_create_tenant_seeds_one_user_per_default_role(monkeypatch):
    sa_email = f"sa-{uuid4().hex[:8]}@example.com"
    monkeypatch.setenv("PLATFORM_SUPERADMIN_EMAIL", sa_email)
    monkeypatch.setenv("PLATFORM_SUPERADMIN_PASSWORD", "supersecret1")
    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": sa_email, "password": "supersecret1"})
        if login.status_code >= 500:
            pytest.skip("database unavailable")
        assert login.status_code == 200, login.text
        sa = _headers(login.json()["access_token"])
        suffix = uuid4().hex[:6]
        slug = f"seed-{suffix}"
        admin_email = f"owner-{suffix}@example.com"
        created = client.post(
            "/api/v1/platform/tenants",
            headers=sa,
            json={
                "name": "Seed Co",
                "slug": slug,
                "admin_name": "Owner",
                "admin_email": admin_email,
                "admin_password": "supersecret1",
            },
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["password_set"] is True
        seeded = body["seeded_users"]
        assert len(seeded) == 3
        by_role = {row["role"]: row for row in seeded}
        assert set(by_role) == {"Tenant Admin", "Member", "Viewer"}
        assert by_role["Tenant Admin"]["email"] == admin_email
        assert by_role["Tenant Admin"]["is_demo"] is False
        assert by_role["Tenant Admin"]["invitation_token"] == body["invitation_token"]
        assert by_role["Member"]["email"] == f"member@{slug}.demo"
        assert by_role["Member"]["name"] == "Member (demo)"
        assert by_role["Member"]["status"] == "invited"
        assert by_role["Member"]["is_demo"] is True
        assert by_role["Member"]["invitation_token"]
        assert by_role["Member"]["invite_path"].startswith("/invite?token=")
        assert by_role["Viewer"]["email"] == f"viewer@{slug}.demo"
        assert by_role["Viewer"]["name"] == "Viewer (demo)"
        assert by_role["Viewer"]["status"] == "invited"
        assert by_role["Viewer"]["invitation_token"]
        assert sum(1 for row in seeded if row["role"] == "Tenant Admin") == 1

        logged = client.post(
            "/api/v1/auth/login",
            json={"email": admin_email, "password": "supersecret1", "tenant_slug": slug},
        )
        assert logged.status_code == 200, logged.text
        admin = _headers(logged.json()["access_token"])
        roles = client.get("/api/v1/roles", headers=admin)
        assert roles.status_code == 200, roles.text
        assert {row["name"] for row in roles.json()} == {"Tenant Admin", "Member", "Viewer"}
        users = client.get("/api/v1/users", headers=admin)
        assert users.status_code == 200, users.text
        rows = users.json()
        assert len(rows) == 3
        by_email = {row["email"]: row for row in rows}
        assert "Tenant Admin" in by_email[admin_email]["roles"]
        assert "Member" in by_email[f"member@{slug}.demo"]["roles"]
        assert "Viewer" in by_email[f"viewer@{slug}.demo"]["roles"]
        assert sum(1 for row in rows if "Tenant Admin" in (row.get("roles") or [])) == 1
        assert by_email[f"member@{slug}.demo"]["status"] == "invited"
        denied = client.post(
            "/api/v1/auth/login",
            json={"email": f"member@{slug}.demo", "password": "supersecret1", "tenant_slug": slug},
        )
        assert denied.status_code in {401, 403}
        accepted = client.post(
            "/api/v1/auth/accept-invite",
            json={"token": by_role["Member"]["invitation_token"], "password": "supersecret1"},
        )
        assert accepted.status_code == 200, accepted.text
        me = client.get("/api/v1/auth/me", headers=_headers(accepted.json()["access_token"]))
        assert me.status_code == 200
        assert "Member" in me.json()["roles"]


def test_demo_member_email_suffixes_when_admin_email_collides(monkeypatch):
    sa_email = f"sa-{uuid4().hex[:8]}@example.com"
    monkeypatch.setenv("PLATFORM_SUPERADMIN_EMAIL", sa_email)
    monkeypatch.setenv("PLATFORM_SUPERADMIN_PASSWORD", "supersecret1")
    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": sa_email, "password": "supersecret1"})
        if login.status_code >= 500:
            pytest.skip("database unavailable")
        assert login.status_code == 200, login.text
        sa = _headers(login.json()["access_token"])
        suffix = uuid4().hex[:6]
        slug = f"hit-{suffix}"
        colliding = f"member@{slug}.demo"
        created = client.post(
            "/api/v1/platform/tenants",
            headers=sa,
            json={
                "name": "Hit Co",
                "slug": slug,
                "admin_name": "Member Demo",
                "admin_email": colliding,
                "admin_password": "supersecret1",
            },
        )
        assert created.status_code == 200, created.text
        seeded = created.json()["seeded_users"]
        by_role = {row["role"]: row for row in seeded}
        assert by_role["Tenant Admin"]["email"] == colliding
        assert by_role["Member"]["email"] == f"member-2@{slug}.demo"
        assert by_role["Viewer"]["email"] == f"viewer@{slug}.demo"
        assert len(seeded) == 3
        assert sum(1 for row in seeded if row["role"] == "Tenant Admin") == 1


def test_tenant_isolation_for_docs_folders_conversations_and_ai_config():
    app = create_app()
    with TestClient(app) as client:
        _email_a, headers_a, _ = _signup(client, prefix="iso-a")
        _email_b, headers_b, _ = _signup(client, prefix="iso-b")
        unique = f"SECRET-{uuid4().hex[:8]}"
        uploaded = client.post(
            "/api/v1/documents",
            headers=headers_a,
            files={"file": ("secret.md", f"# Secret\n{unique} is only for tenant A.\n".encode(), "text/markdown")},
        )
        assert uploaded.status_code == 200, uploaded.text
        doc_id = uploaded.json()["document_id"]

        folder = client.post("/api/v1/folders", headers=headers_a, json={"name": "Legal"})
        assert folder.status_code == 200, folder.text
        folder_id = folder.json()["id"]

        chat_a = client.post("/api/v1/chat", headers=headers_a, json={"question": f"What is {unique}?"})
        assert chat_a.status_code == 200, chat_a.text
        conversation_id = chat_a.json()["conversation_id"]

        listed = client.get("/api/v1/documents", headers=headers_b)
        assert listed.status_code == 200
        assert doc_id not in {row["id"] for row in listed.json()}

        guessed_folder = client.get(f"/api/v1/folders/{folder_id}", headers=headers_b)
        assert guessed_folder.status_code == 404

        conv = client.get(f"/api/v1/conversations/{conversation_id}", headers=headers_b)
        assert conv.status_code == 404

        put_a = client.put(
            "/api/v1/tenant/ai-config",
            headers=headers_a,
            json={"provider": "openai", "model": "gpt-4o-mini", "temperature": 0.5},
        )
        assert put_a.status_code == 200, put_a.text
        get_b = client.get("/api/v1/tenant/ai-config", headers=headers_b)
        assert get_b.status_code == 200, get_b.text
        assert get_b.json()["model"] != "gpt-4o-mini"
        get_a = client.get("/api/v1/tenant/ai-config", headers=headers_a)
        assert get_a.json()["model"] == "gpt-4o-mini"

        same_q = client.post("/api/v1/chat", headers=headers_b, json={"question": f"What is {unique}?"})
        assert same_q.status_code == 200, same_q.text
        assert unique.lower() not in same_q.json()["answer"].lower()


def test_folder_idor_and_share_compile():
    app = create_app()
    with TestClient(app) as client:
        _email_a, headers_a, body_a = _signup(client, prefix="fold-a")
        _email_b, headers_b, _ = _signup(client, prefix="fold-b")
        created = client.post("/api/v1/folders", headers=headers_a, json={"name": "Private"})
        assert created.status_code == 200, created.text
        folder_id = created.json()["id"]
        hidden = client.get(f"/api/v1/folders/{folder_id}", headers=headers_b)
        assert hidden.status_code == 404
        patched = client.patch(
            f"/api/v1/folders/{folder_id}",
            headers=headers_b,
            json={"name": "Hacked"},
        )
        assert patched.status_code == 404

        member = f"sharee-{uuid4().hex[:8]}@example.com"
        invited = client.post(
            "/api/v1/users",
            headers=headers_a,
            json={"email": member, "password": "supersecret1", "role": "Member"},
        )
        assert invited.status_code == 200, invited.text
        shared = client.post(
            f"/api/v1/folders/{folder_id}/share",
            headers=headers_a,
            json={"subject_type": "user", "email": member, "actions": ["view"]},
        )
        assert shared.status_code == 200, shared.text
        login = client.post(
            "/api/v1/auth/login",
            json={"email": member, "password": "supersecret1", "tenant_id": body_a["tenant_id"]},
        )
        assert login.status_code == 200, login.text
        member_headers = _headers(login.json()["access_token"])
        visible = client.get(f"/api/v1/folders/{folder_id}", headers=member_headers)
        assert visible.status_code == 200, visible.text
        assert visible.json()["documents_count"] == 0
        assert visible.json()["grants"]


def test_expired_and_used_invite_rejected(monkeypatch):
    sa_email = f"sa-{uuid4().hex[:8]}@example.com"
    monkeypatch.setenv("PLATFORM_SUPERADMIN_EMAIL", sa_email)
    monkeypatch.setenv("PLATFORM_SUPERADMIN_PASSWORD", "supersecret1")
    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": sa_email, "password": "supersecret1"})
        if login.status_code >= 500:
            pytest.skip("database unavailable")
        assert login.status_code == 200, login.text
        sa = _headers(login.json()["access_token"])
        admin_email = f"once-{uuid4().hex[:8]}@example.com"
        created = client.post(
            "/api/v1/platform/tenants",
            headers=sa,
            json={
                "name": "Once",
                "slug": f"once-{uuid4().hex[:6]}",
                "admin_name": "Once",
                "admin_email": admin_email,
            },
        )
        assert created.status_code == 200, created.text
        token = created.json()["invitation_token"]
        first = client.post("/api/v1/auth/accept-invite", json={"token": token, "password": "supersecret1"})
        assert first.status_code == 200, first.text
        second = client.post("/api/v1/auth/accept-invite", json={"token": token, "password": "supersecret1"})
        assert second.status_code in {400, 422}

        expired_email = f"exp-{uuid4().hex[:8]}@example.com"
        created2 = client.post(
            "/api/v1/platform/tenants",
            headers=sa,
            json={
                "name": "Expired",
                "slug": f"exp-{uuid4().hex[:6]}",
                "admin_name": "Exp",
                "admin_email": expired_email,
            },
        )
        assert created2.status_code == 200, created2.text
        expired_token = created2.json()["invitation_token"]
        _expire_invite(expired_token)
        expired = client.post(
            "/api/v1/auth/accept-invite", json={"token": expired_token, "password": "supersecret1"}
        )
        assert expired.status_code in {400, 422}


def test_disabled_user_cannot_login():
    app = create_app()
    with TestClient(app) as client:
        _admin, admin_headers, body = _signup(client, prefix="dis")
        member = f"dis-{uuid4().hex[:8]}@example.com"
        invited = client.post(
            "/api/v1/users",
            headers=admin_headers,
            json={"email": member, "password": "supersecret1", "role": "Member"},
        )
        assert invited.status_code == 200, invited.text
        user_id = invited.json()["user_id"]
        patched = client.patch(
            f"/api/v1/users/{user_id}",
            headers=admin_headers,
            json={"status": "disabled"},
        )
        assert patched.status_code == 200, patched.text
        login = client.post(
            "/api/v1/auth/login",
            json={"email": member, "password": "supersecret1", "tenant_id": body["tenant_id"]},
        )
        assert login.status_code in {401, 403}


def test_suspended_tenant_cannot_login(monkeypatch):
    sa_email = f"sa-{uuid4().hex[:8]}@example.com"
    monkeypatch.setenv("PLATFORM_SUPERADMIN_EMAIL", sa_email)
    monkeypatch.setenv("PLATFORM_SUPERADMIN_PASSWORD", "supersecret1")
    app = create_app()
    with TestClient(app) as client:
        sa_login = client.post("/api/v1/auth/login", json={"email": sa_email, "password": "supersecret1"})
        if sa_login.status_code >= 500:
            pytest.skip("database unavailable")
        assert sa_login.status_code == 200, sa_login.text
        sa = _headers(sa_login.json()["access_token"])
        slug = f"sus-{uuid4().hex[:6]}"
        admin_email = f"sus-{uuid4().hex[:8]}@example.com"
        created = client.post(
            "/api/v1/platform/tenants",
            headers=sa,
            json={
                "name": "Suspended Co",
                "slug": slug,
                "admin_name": "Sue",
                "admin_email": admin_email,
            },
        )
        assert created.status_code == 200, created.text
        accepted = client.post(
            "/api/v1/auth/accept-invite",
            json={"token": created.json()["invitation_token"], "password": "supersecret1"},
        )
        assert accepted.status_code == 200, accepted.text
        tenant_id = created.json()["tenant"]["id"]
        patched = client.patch(
            f"/api/v1/platform/tenants/{tenant_id}",
            headers=sa,
            json={"status": "suspended"},
        )
        assert patched.status_code == 200, patched.text
        login = client.post(
            "/api/v1/auth/login",
            json={"email": admin_email, "password": "supersecret1", "tenant_slug": slug},
        )
        assert login.status_code in {401, 403}


def test_tenant_a_model_overlay_does_not_change_tenant_b():
    app = create_app()
    with TestClient(app) as client:
        _a, headers_a, _ = _signup(client, prefix="cfg-a")
        _b, headers_b, _ = _signup(client, prefix="cfg-b")
        before = client.get("/api/v1/tenant/ai-config", headers=headers_b)
        if before.status_code >= 500:
            pytest.skip("database unavailable")
        assert before.status_code == 200
        original = before.json()
        updated = client.put(
            "/api/v1/tenant/ai-config",
            headers=headers_a,
            json={"provider": "openai", "model": "gpt-4o-mini"},
        )
        assert updated.status_code == 200, updated.text
        after = client.get("/api/v1/tenant/ai-config", headers=headers_b)
        assert after.status_code == 200
        assert after.json()["provider"] == original["provider"]
        assert after.json()["model"] == original["model"]


def test_rag_still_isolated_across_tenants():
    app = create_app()
    with TestClient(app) as client:
        _email_a, headers_a, _ = _signup(client, prefix="rag-a")
        unique = f"TENANT-A-SECRET-{uuid4().hex[:8]}"
        uploaded = client.post(
            "/api/v1/documents",
            headers=headers_a,
            files={"file": ("secret.md", f"# Secret\n{unique} is only for tenant A.\n".encode(), "text/markdown")},
        )
        if uploaded.status_code >= 500:
            pytest.skip("database unavailable")
        assert uploaded.status_code == 200, uploaded.text
        version_id = uploaded.json()["version_id"]
        _email_b, headers_b, _ = _signup(client, prefix="rag-b")
        guessed = client.post(
            "/api/v1/chat",
            headers=headers_b,
            json={"question": f"What is {unique}?", "version_id": version_id},
        )
        assert guessed.status_code in {200, 404}
        if guessed.status_code == 200:
            assert unique.lower() not in guessed.json()["answer"].lower()
        listed = client.get("/api/v1/documents", headers=headers_b)
        assert uploaded.json()["document_id"] not in {row["id"] for row in listed.json()}


def test_auth_features_and_http_aliases():
    app = create_app()
    with TestClient(app) as client:
        features = client.get("/api/v1/auth/features")
        if features.status_code >= 500:
            pytest.skip("database unavailable")
        assert features.status_code == 200
        assert features.json()["public_signup"] is True

        _email, headers, _ = _signup(client, prefix="alias")
        created_role = client.post(
            "/api/v1/roles",
            headers=headers,
            json={"name": f"Reviewer-{uuid4().hex[:6]}", "description": "d", "permissions": ["folders.view"]},
        )
        assert created_role.status_code == 200, created_role.text
        role_id = created_role.json()["id"]
        put = client.put(
            f"/api/v1/roles/{role_id}",
            headers=headers,
            json={
                "name": f"Editor-{uuid4().hex[:6]}",
                "description": "updated",
                "permissions": ["folders.view", "folders.share"],
            },
        )
        assert put.status_code == 200, put.text
        codes = put.json().get("permission_codes") or put.json().get("permissions") or []
        assert "folders.share" in codes

        folder = client.post("/api/v1/folders", headers=headers, json={"name": "Shared"})
        assert folder.status_code == 200, folder.text
        folder_id = folder.json()["id"]
        member = f"share-alias-{uuid4().hex[:8]}@example.com"
        invited = client.post(
            "/api/v1/users",
            headers=headers,
            json={"email": member, "password": "supersecret1", "role": "Member"},
        )
        assert invited.status_code == 200, invited.text
        shared = client.post(
            f"/api/v1/folders/{folder_id}/share",
            headers=headers,
            json={"subject_type": "user", "email": member, "actions": ["view"]},
        )
        assert shared.status_code == 200, shared.text
        via_share = client.delete(
            f"/api/v1/folders/{folder_id}/share/{shared.json()['id']}",
            headers=headers,
        )
        assert via_share.status_code == 200, via_share.text

        shared2 = client.post(
            f"/api/v1/folders/{folder_id}/share",
            headers=headers,
            json={"subject_type": "user", "email": member, "actions": ["view"]},
        )
        assert shared2.status_code == 200, shared2.text
        via_grants = client.delete(
            f"/api/v1/folders/{folder_id}/grants/{shared2.json()['id']}",
            headers=headers,
        )
        assert via_grants.status_code == 200, via_grants.text
        detail = client.get(f"/api/v1/folders/{folder_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["grants"] == []


def test_auth_features_respects_signup_flag(monkeypatch):
    monkeypatch.setenv("RAG_ALLOW_PUBLIC_SIGNUP", "0")
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/features")
        if response.status_code >= 500:
            pytest.skip("database unavailable")
        assert response.status_code == 200
        assert response.json()["public_signup"] is False


def test_platform_audit_logs_super_admin_only_no_document_dump(monkeypatch):
    sa_email = f"sa-{uuid4().hex[:8]}@example.com"
    monkeypatch.setenv("PLATFORM_SUPERADMIN_EMAIL", sa_email)
    monkeypatch.setenv("PLATFORM_SUPERADMIN_PASSWORD", "supersecret1")
    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": sa_email, "password": "supersecret1"})
        if login.status_code >= 500:
            pytest.skip("database unavailable")
        assert login.status_code == 200, login.text
        sa = _headers(login.json()["access_token"])

        _email, tenant_headers, _ = _signup(client, prefix="aud-ta")
        denied = client.get("/api/v1/platform/audit-logs", headers=tenant_headers)
        assert denied.status_code == 403

        unique = f"DOC-SECRET-{uuid4().hex[:8]}"
        uploaded = client.post(
            "/api/v1/documents",
            headers=tenant_headers,
            files={"file": ("secret.md", f"# Secret\n{unique} must not leak.\n".encode(), "text/markdown")},
        )
        assert uploaded.status_code == 200, uploaded.text

        slug = f"aud-{uuid4().hex[:6]}"
        created = client.post(
            "/api/v1/platform/tenants",
            headers=sa,
            json={
                "name": "Audit Co",
                "slug": slug,
                "admin_name": "Aud",
                "admin_email": f"aud-{uuid4().hex[:8]}@example.com",
            },
        )
        assert created.status_code == 200, created.text
        tenant_id = created.json()["tenant"]["id"]
        suspended = client.patch(
            f"/api/v1/platform/tenants/{tenant_id}",
            headers=sa,
            json={"status": "suspended"},
        )
        assert suspended.status_code == 200, suspended.text

        logs = client.get("/api/v1/platform/audit-logs", headers=sa)
        assert logs.status_code == 200, logs.text
        payload = logs.json()
        assert unique not in str(payload)
        rows = payload if isinstance(payload, list) else payload.get("items") or payload.get("logs") or []
        actions = {row.get("action") for row in rows}
        assert "tenant.create" in actions or "tenant.suspend" in actions
        assert all((row.get("resource_type") or "") != "document" for row in rows)
