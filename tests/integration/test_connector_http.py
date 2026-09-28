from uuid import uuid4

import pytest
from app.main import create_app
from fastapi.testclient import TestClient


def test_mock_google_drive_connect_subscribe_sync(monkeypatch):
    monkeypatch.setenv("RAG_CONNECTOR_MOCKS", "1")
    app = create_app()
    with TestClient(app) as client:
        email = f"conn-{uuid4().hex[:8]}@example.com"
        signup = client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "supersecret1", "tenant_name": f"T{uuid4().hex[:6]}"},
        )
        if signup.status_code >= 500:
            pytest.skip("database unavailable")
        assert signup.status_code == 200, signup.text
        token = signup.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        catalog = client.get("/api/v1/connectors/catalog", headers=headers)
        assert catalog.status_code == 200
        ids = {row["id"] for row in catalog.json()}
        assert "mock_google_drive" in ids

        start = client.post(
            "/api/v1/connectors/oauth/start",
            headers=headers,
            json={"connector_type": "mock_google_drive", "redirect_uri": "http://127.0.0.1:5173/sources"},
        )
        assert start.status_code == 200, start.text
        body = start.json()
        assert "state" in body and "mock-granted" in body["authorization_url"]

        connected = client.post(
            "/api/v1/connectors/oauth/callback",
            headers=headers,
            json={"code": "mock-granted", "state": body["state"]},
        )
        assert connected.status_code == 200, connected.text
        source_id = connected.json()["id"]

        children = client.get(f"/api/v1/connectors/{source_id}/locations/root/children", headers=headers)
        assert children.status_code == 200
        folders = [c for c in children.json() if c["kind"] == "folder"]
        assert folders
        eng = next(f for f in folders if f["name"] == "Engineering")

        subscribed = client.post(
            f"/api/v1/connectors/{source_id}/subscriptions",
            headers=headers,
            json={"location_id": eng["id"], "location_name": eng["name"], "include_subfolders": True},
        )
        assert subscribed.status_code == 200, subscribed.text
        sync = subscribed.json()["sync"]
        assert sync["status"] == "completed"
        assert sync["files_added"] >= 1
        assert sync["files_failed"] == 0

        docs = client.get("/api/v1/documents", headers=headers)
        assert docs.status_code == 200
        titles = {d["title"] for d in docs.json()}
        assert "architecture.md" in titles

        again = client.post(
            f"/api/v1/subscriptions/{subscribed.json()['subscription']['id']}/sync",
            headers=headers,
        )
        assert again.status_code == 200
        assert again.json()["files_skipped"] >= 1

        from app.adapters.providers.connectors.mock import MockGoogleDriveConnector

        async def _empty(self):
            return []

        monkeypatch.setattr(MockGoogleDriveConnector, "list_files", _empty)
        deleted = client.post(
            f"/api/v1/subscriptions/{subscribed.json()['subscription']['id']}/sync",
            headers=headers,
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["files_deleted"] >= 1
        docs_removed = client.get("/api/v1/documents", headers=headers)
        assert docs_removed.status_code == 200
        assert "architecture.md" not in {d["title"] for d in docs_removed.json()}
        listed_after_delete = client.get("/api/v1/connectors", headers=headers)
        mock_after_delete = next(row for row in listed_after_delete.json() if row["id"] == source_id)
        assert mock_after_delete["document_count"] == 0

        start2 = client.post(
            "/api/v1/connectors/oauth/start",
            headers=headers,
            json={"connector_type": "mock_google_drive", "redirect_uri": "http://127.0.0.1:5173/sources"},
        )
        assert start2.status_code == 200, start2.text
        again_login = client.post(
            "/api/v1/connectors/oauth/callback",
            headers=headers,
            json={"code": "mock-granted", "state": start2.json()["state"]},
        )
        assert again_login.status_code == 200, again_login.text
        assert again_login.json()["id"] == source_id
        assert again_login.json()["reused"] is True
        listed_after_login = client.get("/api/v1/connectors", headers=headers)
        assert listed_after_login.status_code == 200
        mock_rows = [row for row in listed_after_login.json() if row["connector_type"] == "mock_google_drive"]
        assert len(mock_rows) == 1

        gone = client.delete(f"/api/v1/connectors/{source_id}", headers=headers)
        assert gone.status_code == 200, gone.text
        listed = client.get("/api/v1/connectors", headers=headers)
        assert listed.status_code == 200
        assert source_id not in {row["id"] for row in listed.json()}
        docs_after = client.get("/api/v1/documents", headers=headers)
        assert docs_after.status_code == 200
        assert "architecture.md" not in {d["title"] for d in docs_after.json()}


def test_saved_oauth_client_starts_google_login(monkeypatch):
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("RAG_CONNECTOR_MOCKS", raising=False)
    app = create_app()
    with TestClient(app) as client:
        email = f"oauth-{uuid4().hex[:8]}@example.com"
        signup = client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "supersecret1", "tenant_name": f"T{uuid4().hex[:6]}"},
        )
        if signup.status_code >= 500:
            pytest.skip("database unavailable")
        assert signup.status_code == 200, signup.text
        headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}

        catalog = client.get("/api/v1/connectors/catalog", headers=headers)
        assert catalog.status_code == 200
        drive = next(row for row in catalog.json() if row["id"] == "google_drive")
        assert drive["configured"] is False

        saved = client.put(
            "/api/v1/connectors/oauth/clients",
            headers=headers,
            json={"google": {"client_id": "gid.apps.googleusercontent.com", "client_secret": "gsecret"}},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["clients"]["google"]["configured"] is True
        assert "client_secret" not in saved.json()["clients"]["google"]

        catalog2 = client.get("/api/v1/connectors/catalog", headers=headers)
        drive2 = next(row for row in catalog2.json() if row["id"] == "google_drive")
        assert drive2["configured"] is True

        start = client.post(
            "/api/v1/connectors/oauth/start",
            headers=headers,
            json={"connector_type": "google_drive", "redirect_uri": "http://127.0.0.1:5173/sources"},
        )
        assert start.status_code == 200, start.text
        url = start.json()["authorization_url"]
        assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
        assert "gid.apps.googleusercontent.com" in url
