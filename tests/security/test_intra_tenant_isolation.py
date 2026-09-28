from uuid import uuid4

import pytest
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
    body = signup.json()
    return email, {"Authorization": f"Bearer {body['access_token']}"}, body


def _login(client: TestClient, email: str, tenant_id: str, password: str = "supersecret1"):
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "tenant_id": tenant_id},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _invite(client: TestClient, admin_headers: dict, email: str) -> None:
    invited = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={"email": email, "password": "supersecret1", "role": "Member"},
    )
    assert invited.status_code == 200, invited.text


def _connect_mock_drive(client: TestClient, headers: dict) -> tuple[str, str]:
    start = client.post(
        "/api/v1/connectors/oauth/start",
        headers=headers,
        json={"connector_type": "mock_google_drive", "redirect_uri": "http://127.0.0.1:5173/sources"},
    )
    assert start.status_code == 200, start.text
    connected = client.post(
        "/api/v1/connectors/oauth/callback",
        headers=headers,
        json={"code": "mock-granted", "state": start.json()["state"]},
    )
    assert connected.status_code == 200, connected.text
    source_id = connected.json()["id"]
    children = client.get(f"/api/v1/connectors/{source_id}/locations/root/children", headers=headers)
    assert children.status_code == 200, children.text
    eng = next(row for row in children.json() if row["name"] == "Engineering")
    subscribed = client.post(
        f"/api/v1/connectors/{source_id}/subscriptions",
        headers=headers,
        json={"location_id": eng["id"], "location_name": eng["name"], "include_subfolders": True},
    )
    assert subscribed.status_code == 200, subscribed.text
    assert subscribed.json()["sync"]["status"] == "completed"
    return source_id, subscribed.json()["subscription"]["id"]


def test_same_tenant_members_cannot_see_unshared_docs_or_connectors(monkeypatch):
    monkeypatch.setenv("RAG_CONNECTOR_MOCKS", "1")
    app = create_app()
    with TestClient(app) as client:
        _admin_email, admin_headers, admin_body = _signup(client, prefix="mts-admin")
        tenant_id = admin_body["tenant_id"]
        member1 = f"m1-{uuid4().hex[:8]}@example.com"
        member2 = f"m2-{uuid4().hex[:8]}@example.com"
        _invite(client, admin_headers, member1)
        _invite(client, admin_headers, member2)
        headers1 = _login(client, member1, tenant_id)
        headers2 = _login(client, member2, tenant_id)

        source_id, _sub_id = _connect_mock_drive(client, headers1)
        docs1 = client.get("/api/v1/documents", headers=headers1)
        assert docs1.status_code == 200
        titles1 = {row["title"] for row in docs1.json()}
        assert "architecture.md" in titles1
        doc = next(row for row in docs1.json() if row["title"] == "architecture.md")

        docs2 = client.get("/api/v1/documents", headers=headers2)
        assert docs2.status_code == 200
        assert "architecture.md" not in {row["title"] for row in docs2.json()}
        hidden = client.get(f"/api/v1/documents/{doc['id']}/versions", headers=headers2)
        assert hidden.status_code == 404

        catalog = client.post("/api/v1/chat", headers=headers2, json={"question": "how many documents do we have"})
        assert catalog.status_code == 200, catalog.text
        answer = catalog.json()["answer"].lower()
        assert "architecture.md" not in answer

        leaked = client.post(
            "/api/v1/chat",
            headers=headers2,
            json={"question": "What is Asset Hierarchy used for?"},
        )
        assert leaked.status_code == 200, leaked.text
        assert "parent-child" not in leaked.json()["answer"].lower()

        listed = client.get("/api/v1/connectors", headers=headers2)
        assert listed.status_code == 200
        assert source_id not in {row["id"] for row in listed.json()}
        browse = client.get(f"/api/v1/connectors/{source_id}/locations/root/children", headers=headers2)
        assert browse.status_code in {403, 404}

        oauth_save = client.put(
            "/api/v1/connectors/oauth/clients",
            headers=headers2,
            json={"google": {"client_id": "gid.apps.googleusercontent.com", "client_secret": "gsecret"}},
        )
        assert oauth_save.status_code == 403

        jobs2 = client.get("/api/v1/jobs", headers=headers2)
        assert jobs2.status_code == 200
        assert doc["id"] not in {row.get("document_id") for row in jobs2.json()}

        shared = client.post(
            f"/api/v1/documents/{doc['id']}/acl",
            headers=headers1,
            json={"emails": [member2]},
        )
        assert shared.status_code == 200, shared.text

        docs2b = client.get("/api/v1/documents", headers=headers2)
        assert docs2b.status_code == 200
        assert "architecture.md" in {row["title"] for row in docs2b.json()}
        visible = client.get(f"/api/v1/documents/{doc['id']}/versions", headers=headers2)
        assert visible.status_code == 200

        retrieved = client.post(
            "/api/v1/chat",
            headers=headers2,
            json={"question": "What is Asset Hierarchy used for?"},
        )
        assert retrieved.status_code == 200, retrieved.text
        assert "parent-child" in retrieved.json()["answer"].lower()

        still_hidden = client.get(f"/api/v1/connectors/{source_id}/locations/root/children", headers=headers2)
        assert still_hidden.status_code in {403, 404}

        resync = client.post(f"/api/v1/subscriptions/{_sub_id}/sync", headers=headers1)
        assert resync.status_code == 200, resync.text
        docs2c = client.get("/api/v1/documents", headers=headers2)
        assert docs2c.status_code == 200
        assert "architecture.md" in {row["title"] for row in docs2c.json()}
