from __future__ import annotations

from uuid import uuid4

import pytest
from app.main import create_app
from fastapi.testclient import TestClient


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


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
    return email, _headers(body["access_token"]), body


def _login(client: TestClient, email: str, *, tenant_id: str | None = None, tenant_slug: str | None = None):
    payload: dict = {"email": email, "password": "supersecret1"}
    if tenant_id:
        payload["tenant_id"] = tenant_id
    if tenant_slug:
        payload["tenant_slug"] = tenant_slug
    login = client.post("/api/v1/auth/login", json=payload)
    assert login.status_code == 200, login.text
    return _headers(login.json()["access_token"])


def _invite_named(client: TestClient, admin: dict, role: str) -> tuple[str, dict]:
    email = f"{role.lower()}-{uuid4().hex[:8]}@example.com"
    invited = client.post(
        "/api/v1/users",
        headers=admin,
        json={"email": email, "password": "supersecret1", "role": role},
    )
    assert invited.status_code == 200, invited.text
    return email, invited.json()


TENANT_PROTECTED = (
    ("GET", "/api/v1/documents"),
    ("GET", "/api/v1/folders"),
    ("GET", "/api/v1/users"),
    ("GET", "/api/v1/roles"),
    ("GET", "/api/v1/conversations"),
    ("GET", "/api/v1/config"),
    ("GET", "/api/v1/tenant/ai-config"),
    ("GET", "/api/v1/audit-logs"),
    ("POST", "/api/v1/chat"),
)


def test_unauthenticated_requests_are_401():
    app = create_app()
    with TestClient(app) as client:
        live = client.get("/api/v1/health/live")
        if live.status_code >= 500:
            pytest.skip("database unavailable")
        assert live.status_code == 200
        for method, path in TENANT_PROTECTED:
            response = client.request(method, path, json={"question": "hi"} if path.endswith("/chat") else None)
            assert response.status_code == 401, f"{method} {path} -> {response.status_code} {response.text}"
        assert client.get("/api/v1/platform/tenants").status_code == 401


def test_super_admin_is_denied_tenant_document_apis(monkeypatch):
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
        body = me.json()
        assert body["is_super_admin"] is True
        assert body["tenant_id"] is None
        assert "document:read_all" not in (body.get("permissions") or [])
        assert body.get("permissions") == []

        for method, path in TENANT_PROTECTED:
            kwargs = {"headers": sa}
            if path.endswith("/chat"):
                kwargs["json"] = {"question": "leak tenant secrets"}
            response = client.request(method, path, **kwargs)
            assert response.status_code in {401, 403}, f"{method} {path} -> {response.status_code} {response.text}"

        listed = client.get("/api/v1/platform/tenants", headers=sa)
        assert listed.status_code == 200
        switch = client.post("/api/v1/auth/switch-tenant", headers=sa, json={"tenant_id": str(uuid4())})
        assert switch.status_code == 403


def test_viewer_and_member_cannot_manage_users_or_platform():
    app = create_app()
    with TestClient(app) as client:
        _admin_email, admin, body = _signup(client, prefix="rbac-ta")
        tenant_id = body["tenant_id"]
        viewer_email, _ = _invite_named(client, admin, "Viewer")
        member_email, _ = _invite_named(client, admin, "Member")
        viewer = _login(client, viewer_email, tenant_id=tenant_id)
        member = _login(client, member_email, tenant_id=tenant_id)

        me_v = client.get("/api/v1/auth/me", headers=viewer).json()
        assert "Viewer" in me_v["roles"]
        assert "document:read_all" not in me_v["permissions"]
        me_m = client.get("/api/v1/auth/me", headers=member).json()
        assert "Member" in me_m["roles"]
        assert "document:read_all" not in me_m["permissions"]

        for headers in (viewer, member):
            assert client.get("/api/v1/users", headers=headers).status_code == 403
            assert client.post(
                "/api/v1/users",
                headers=headers,
                json={"email": f"nope-{uuid4().hex[:8]}@example.com", "password": "supersecret1", "role": "Member"},
            ).status_code == 403
            assert client.post(
                "/api/v1/users/invitations",
                headers=headers,
                json={"email": f"nope-{uuid4().hex[:8]}@example.com", "name": "Nope"},
            ).status_code == 403
            assert client.patch(
                f"/api/v1/users/{uuid4()}",
                headers=headers,
                json={"name": "Nope"},
            ).status_code == 403
            assert client.post(
                f"/api/v1/users/{uuid4()}/resend-invite",
                headers=headers,
            ).status_code == 403
            assert client.post(
                "/api/v1/platform/tenants",
                headers=headers,
                json={
                    "name": "Nope",
                    "slug": f"nope-{uuid4().hex[:6]}",
                    "admin_name": "Ada",
                    "admin_email": f"ada-{uuid4().hex[:8]}@example.com",
                },
            ).status_code == 403

        assert client.post("/api/v1/folders", headers=viewer, json={"name": "Denied"}).status_code == 403
        created = client.post("/api/v1/folders", headers=member, json={"name": "Member folder"})
        assert created.status_code == 200, created.text


def test_custom_users_create_cannot_disable_or_grant_read_all():
    app = create_app()
    with TestClient(app) as client:
        _admin_email, admin, body = _signup(client, prefix="rbac-custom")
        tenant_id = body["tenant_id"]
        role = client.post(
            "/api/v1/roles",
            headers=admin,
            json={"name": f"Inviter-{uuid4().hex[:6]}", "permissions": ["users.view", "users.create"]},
        )
        assert role.status_code == 200, role.text
        assert "permissions" in role.json()
        assert "permission_codes" in role.json()
        inviter_email, _ = _invite_named(client, admin, role.json()["name"])
        inviter = _login(client, inviter_email, tenant_id=tenant_id)

        invite = client.post(
            "/api/v1/users/invitations",
            headers=inviter,
            json={"email": f"new-{uuid4().hex[:8]}@example.com", "name": "New", "roles": ["Member"]},
        )
        assert invite.status_code == 200, invite.text

        password_invite = client.post(
            "/api/v1/users",
            headers=inviter,
            json={"email": f"pw-{uuid4().hex[:8]}@example.com", "password": "supersecret1", "role": "Member"},
        )
        assert password_invite.status_code == 403

        users = client.get("/api/v1/users", headers=admin)
        assert users.status_code == 200
        victim = next(row for row in users.json() if row["email"] == inviter_email)
        patched = client.patch(
            f"/api/v1/users/{victim['id']}",
            headers=inviter,
            json={"status": "disabled"},
        )
        assert patched.status_code == 403

        escalated = client.post(
            "/api/v1/roles",
            headers=inviter,
            json={"name": f"God-{uuid4().hex[:6]}", "permissions": ["document:read_all"]},
        )
        assert escalated.status_code == 403

        assert client.get("/api/v1/documents", headers=inviter).status_code == 403
        assert client.post("/api/v1/chat", headers=inviter, json={"question": "hi"}).status_code == 403


def test_cannot_wipe_tenant_admin_role_or_grant_unowned_permission():
    app = create_app()
    with TestClient(app) as client:
        _email, admin, _ = _signup(client, prefix="rbac-sys")
        roles = client.get("/api/v1/roles", headers=admin)
        assert roles.status_code == 200, roles.text
        admin_role = next(row for row in roles.json() if row["name"] == "Tenant Admin")
        assert admin_role["permission_codes"]
        wiped = client.put(
            f"/api/v1/roles/{admin_role['id']}",
            headers=admin,
            json={"permissions": []},
        )
        assert wiped.status_code == 403

        limited = client.post(
            "/api/v1/roles",
            headers=admin,
            json={"name": f"Editor-{uuid4().hex[:6]}", "permissions": ["roles.update", "roles.view", "documents.view"]},
        )
        assert limited.status_code == 200, limited.text
        editor_email, _ = _invite_named(client, admin, limited.json()["name"])
        editor = _login(client, editor_email, tenant_id=client.get("/api/v1/auth/me", headers=admin).json()["tenant_id"])
        steal = client.put(
            f"/api/v1/roles/{limited.json()['id']}",
            headers=editor,
            json={"permissions": ["roles.update", "document:read_all"]},
        )
        assert steal.status_code == 403


def test_folder_share_accepts_ui_payload_and_cross_tenant_idor():
    app = create_app()
    with TestClient(app) as client:
        _email_a, headers_a, body_a = _signup(client, prefix="share-ui-a")
        _email_b, headers_b, _ = _signup(client, prefix="share-ui-b")
        folder = client.post("/api/v1/folders", headers=headers_a, json={"name": "Legal"})
        assert folder.status_code == 200, folder.text
        folder_id = folder.json()["id"]
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
            json={
                "type": "user",
                "email": member,
                "permissions": {"view": True, "edit": False, "upload": False, "delete": False, "share": False},
            },
        )
        assert shared.status_code == 200, shared.text
        assert shared.json()["subject_type"] == "user"
        assert "view" in shared.json()["actions"]

        other = client.post(
            f"/api/v1/folders/{folder_id}/share",
            headers=headers_b,
            json={"subject_type": "user", "email": member, "actions": ["view"]},
        )
        assert other.status_code == 404

        users_b = client.get("/api/v1/users", headers=headers_b)
        assert users_b.status_code == 200
        assert invited.json()["user_id"] not in {row["id"] for row in users_b.json()}
        assert client.patch(
            f"/api/v1/users/{invited.json()['user_id']}",
            headers=headers_b,
            json={"status": "disabled"},
        ).status_code == 404

        login = client.post(
            "/api/v1/auth/login",
            json={"email": member, "password": "supersecret1", "tenant_id": body_a["tenant_id"]},
        )
        assert login.status_code == 200
        member_headers = _headers(login.json()["access_token"])
        visible = client.get(f"/api/v1/folders/{folder_id}", headers=member_headers)
        assert visible.status_code == 200
