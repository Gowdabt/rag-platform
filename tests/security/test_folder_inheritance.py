from pathlib import Path
from uuid import uuid4

import pytest
from app.application.authz import can_read_document
from app.core.context import RequestContext
from app.main import create_app
from fastapi.testclient import TestClient


def _signup(client: TestClient, *, prefix: str):
    email = f"{prefix}-{uuid4().hex[:8]}@example.com"
    signup = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "supersecret1", "tenant_name": f"{prefix}{uuid4().hex[:6]}"},
    )
    if signup.status_code >= 500:
        pytest.skip("database unavailable")
    assert signup.status_code == 200, signup.text
    return email, {"Authorization": f"Bearer {signup.json()['access_token']}"}, signup.json()


def test_folder_acl_model_is_documented_and_deny_by_default():
    text = (Path(__file__).resolve().parents[2] / "backend/app/application/folders.py").read_text(encoding="utf-8")
    assert "Empty document ACL denies" in text
    assert "inherit down the parent chain" in text
    assert "Moving a folder recompiles" in text
    assert "folder_grant_users" in text
    ctx = RequestContext(request_id="t", user_id=uuid4(), permissions=frozenset({"document:read"}))
    assert not can_read_document({}, ctx)
    assert not can_read_document(None, ctx)


def test_folder_child_inherit_move_and_revoke():
    app = create_app()
    with TestClient(app) as client:
        _admin, headers, body = _signup(client, prefix="finh")
        parent = client.post("/api/v1/folders", headers=headers, json={"name": "Parent"})
        assert parent.status_code == 200, parent.text
        parent_id = parent.json()["id"]
        child = client.post("/api/v1/folders", headers=headers, json={"name": "Child", "parent_id": parent_id})
        assert child.status_code == 200, child.text
        child_id = child.json()["id"]

        member = f"finh-{uuid4().hex[:8]}@example.com"
        invited = client.post(
            "/api/v1/users",
            headers=headers,
            json={"email": member, "password": "supersecret1", "role": "Member"},
        )
        assert invited.status_code == 200, invited.text
        shared = client.post(
            f"/api/v1/folders/{parent_id}/share",
            headers=headers,
            json={"subject_type": "user", "email": member, "actions": ["view"]},
        )
        assert shared.status_code == 200, shared.text
        login = client.post(
            "/api/v1/auth/login",
            json={"email": member, "password": "supersecret1", "tenant_id": body["tenant_id"]},
        )
        assert login.status_code == 200, login.text
        member_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.get(f"/api/v1/folders/{parent_id}", headers=member_headers).status_code == 200
        assert client.get(f"/api/v1/folders/{child_id}", headers=member_headers).status_code == 200

        other = client.post("/api/v1/folders", headers=headers, json={"name": "Elsewhere"})
        assert other.status_code == 200, other.text
        moved_folder = client.patch(
            f"/api/v1/folders/{child_id}",
            headers=headers,
            json={"parent_id": other.json()["id"]},
        )
        assert moved_folder.status_code == 200, moved_folder.text
        assert client.get(f"/api/v1/folders/{child_id}", headers=member_headers).status_code == 404

        grant_id = shared.json()["id"]
        revoked = client.delete(f"/api/v1/folders/{parent_id}/grants/{grant_id}", headers=headers)
        assert revoked.status_code == 200, revoked.text
        assert client.get(f"/api/v1/folders/{parent_id}", headers=member_headers).status_code == 404
