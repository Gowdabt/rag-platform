from pathlib import Path
from uuid import uuid4

import pytest
from app.main import create_app
from fastapi.testclient import TestClient


def test_real_local_folder_connect_subscribe_sync(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CONNECTOR_FS_ROOTS", str(tmp_path))
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "handbook.md").write_text("Full-time employees receive 18 PTO days each year.\n", encoding="utf-8")

    app = create_app()
    with TestClient(app) as client:
        email = f"fs-{uuid4().hex[:8]}@example.com"
        signup = client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "supersecret1", "tenant_name": f"FS{uuid4().hex[:6]}"},
        )
        if signup.status_code >= 500:
            pytest.skip("database unavailable")
        assert signup.status_code == 200, signup.text
        headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}

        catalog = client.get("/api/v1/connectors/catalog", headers=headers)
        assert catalog.status_code == 200
        ids = {row["id"] for row in catalog.json()}
        assert "local_fs" in ids
        assert "google_drive" in ids

        created = client.post(
            "/api/v1/connectors",
            headers=headers,
            json={"connector_type": "local_fs", "name": "Laptop docs", "connector_config": {"root_path": str(tmp_path)}},
        )
        assert created.status_code == 200, created.text
        source_id = created.json()["id"]

        children = client.get(f"/api/v1/connectors/{source_id}/locations/root/children", headers=headers)
        assert children.status_code == 200, children.text
        folder = next(row for row in children.json() if row["name"] == "knowledge")

        subscribed = client.post(
            f"/api/v1/connectors/{source_id}/subscriptions",
            headers=headers,
            json={"location_id": folder["id"], "location_name": folder["name"], "include_subfolders": True},
        )
        assert subscribed.status_code == 200, subscribed.text
        sync = subscribed.json()["sync"]
        assert sync["status"] == "completed", sync.get("error_message") or sync
        assert sync["files_added"] >= 1

        docs = client.get("/api/v1/documents", headers=headers)
        assert docs.status_code == 200
        titles = {d["title"] for d in docs.json()}
        assert "handbook.md" in titles


def test_local_fs_host_folder_picker(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CONNECTOR_FS_ROOTS", str(tmp_path))
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "handbook.md").write_text("Full-time employees receive 18 PTO days each year.\n", encoding="utf-8")

    app = create_app()
    with TestClient(app) as client:
        email = f"fs-{uuid4().hex[:8]}@example.com"
        signup = client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "supersecret1", "tenant_name": f"FS{uuid4().hex[:6]}"},
        )
        if signup.status_code >= 500:
            pytest.skip("database unavailable")
        assert signup.status_code == 200, signup.text
        headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}

        roots = client.get("/api/v1/connectors/local-fs/browse", headers=headers)
        assert roots.status_code == 200, roots.text
        body = roots.json()
        assert body["at_roots"] is True
        assert any(row["path"] == str(tmp_path.resolve()) for row in body["items"])

        nested = client.get(
            "/api/v1/connectors/local-fs/browse",
            headers=headers,
            params={"path": str(tmp_path)},
        )
        assert nested.status_code == 200, nested.text
        names = {row["name"] for row in nested.json()["items"]}
        assert "knowledge" in names

        denied = client.get(
            "/api/v1/connectors/local-fs/browse",
            headers=headers,
            params={"path": "/etc"},
        )
        assert denied.status_code == 422
