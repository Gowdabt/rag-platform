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


def _role_id(client: TestClient, admin: dict, name: str) -> str:
    roles = client.get("/api/v1/roles", headers=admin)
    assert roles.status_code == 200, roles.text
    return next(row["id"] for row in roles.json() if row["name"] == name)


def test_tenant_admin_can_patch_name_and_role_member_cannot():
    app = create_app()
    with TestClient(app) as client:
        _admin_email, admin, body = _signup(client, prefix="usr-patch")
        member_email = f"mem-{uuid4().hex[:8]}@example.com"
        invited = client.post(
            "/api/v1/users",
            headers=admin,
            json={"email": member_email, "password": "supersecret1", "role": "Member"},
        )
        assert invited.status_code == 200, invited.text
        user_id = invited.json()["user_id"]
        viewer_id = _role_id(client, admin, "Viewer")
        patched = client.patch(
            f"/api/v1/users/{user_id}",
            headers=admin,
            json={"name": "Pat Member", "role_ids": [viewer_id]},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["name"] == "Pat Member"
        assert patched.json()["roles"] == ["Viewer"]

        login = client.post(
            "/api/v1/auth/login",
            json={"email": member_email, "password": "supersecret1", "tenant_id": body["tenant_id"]},
        )
        assert login.status_code == 200, login.text
        member = _headers(login.json()["access_token"])
        admin_id = client.get("/api/v1/auth/me", headers=admin).json()["user_id"]
        assert (
            client.patch(f"/api/v1/users/{admin_id}", headers=member, json={"name": "Hacked"}).status_code
            == 403
        )
        assert client.post(f"/api/v1/users/{user_id}/resend-invite", headers=member).status_code == 403


def test_resend_invite_returns_new_token_and_invalidates_old():
    app = create_app()
    with TestClient(app) as client:
        _admin_email, admin, _ = _signup(client, prefix="usr-rsnd")
        email = f"inv-{uuid4().hex[:8]}@example.com"
        created = client.post(
            "/api/v1/users/invitations",
            headers=admin,
            json={"email": email, "name": "Invited", "roles": ["Member"]},
        )
        assert created.status_code == 200, created.text
        old_token = created.json().get("invitation_token")
        user_id = created.json()["user_id"]
        assert old_token
        resend = client.post(f"/api/v1/users/{user_id}/resend-invite", headers=admin)
        assert resend.status_code == 200, resend.text
        new_token = resend.json().get("invitation_token")
        assert new_token
        assert new_token != old_token
        assert resend.json().get("invite_path", "").startswith("/invite?token=")
        old_accept = client.post(
            "/api/v1/auth/accept-invite",
            json={"token": old_token, "password": "supersecret1"},
        )
        assert old_accept.status_code in {400, 422}
        accepted = client.post(
            "/api/v1/auth/accept-invite",
            json={"token": new_token, "password": "supersecret1"},
        )
        assert accepted.status_code == 200, accepted.text
        after = client.post(f"/api/v1/users/{user_id}/resend-invite", headers=admin)
        assert after.status_code in {400, 422}


def test_last_tenant_admin_cannot_demote_self():
    app = create_app()
    with TestClient(app) as client:
        _admin_email, admin, _ = _signup(client, prefix="usr-last")
        me = client.get("/api/v1/auth/me", headers=admin)
        assert me.status_code == 200, me.text
        admin_user_id = me.json()["user_id"]
        member_role = _role_id(client, admin, "Member")
        denied = client.patch(
            f"/api/v1/users/{admin_user_id}",
            headers=admin,
            json={"role_ids": [member_role]},
        )
        assert denied.status_code == 409, denied.text

        other = f"adm2-{uuid4().hex[:8]}@example.com"
        second = client.post(
            "/api/v1/users",
            headers=admin,
            json={"email": other, "password": "supersecret1", "role": "Tenant Admin"},
        )
        assert second.status_code == 200, second.text
        allowed = client.patch(
            f"/api/v1/users/{admin_user_id}",
            headers=admin,
            json={"role_ids": [member_role]},
        )
        assert allowed.status_code == 200, allowed.text
        assert "Tenant Admin" not in allowed.json()["roles"]
        assert "Member" in allowed.json()["roles"]
