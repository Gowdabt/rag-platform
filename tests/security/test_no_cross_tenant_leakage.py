from __future__ import annotations

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
    return email, {"Authorization": f"Bearer {signup.json()['access_token']}"}, signup.json()


def test_no_cross_tenant_information_leakage():
    app = create_app()
    with TestClient(app) as client:
        _email_a, headers_a, _ = _signup(client, prefix="leak-a")
        unique = f"CROSS-SECRET-{uuid4().hex[:8]}"
        uploaded = client.post(
            "/api/v1/documents",
            headers=headers_a,
            files={"file": ("secret.md", f"# Secret\n{unique} stays in tenant A.\n".encode(), "text/markdown")},
        )
        assert uploaded.status_code == 200, uploaded.text
        doc_id = uploaded.json()["document_id"]
        version_id = uploaded.json()["version_id"]

        folder = client.post("/api/v1/folders", headers=headers_a, json={"name": "Legal"})
        assert folder.status_code == 200, folder.text
        folder_id = folder.json()["id"]

        chat_a = client.post("/api/v1/chat", headers=headers_a, json={"question": f"What is {unique}?"})
        assert chat_a.status_code == 200, chat_a.text
        conversation_id = chat_a.json()["conversation_id"]
        citations = chat_a.json().get("citations") or []
        assert any(c.get("document_id") == doc_id for c in citations) or unique.lower() in chat_a.json()["answer"].lower()

        connector = client.post(
            "/api/v1/connectors",
            headers=headers_a,
            json={"connector_type": "local_fs", "name": "A files"},
        )
        assert connector.status_code == 200, connector.text
        source_id = connector.json()["id"]
        assert "access_token" not in connector.text
        assert "secret_key" not in connector.text

        role = client.post(
            "/api/v1/roles",
            headers=headers_a,
            json={"name": f"Counsel-{uuid4().hex[:6]}", "permissions": ["folders.view"]},
        )
        assert role.status_code == 200, role.text
        role_id = role.json()["id"]

        _email_b, headers_b, _ = _signup(client, prefix="leak-b")

        listed = client.get("/api/v1/documents", headers=headers_b)
        assert listed.status_code == 200
        assert doc_id not in {row["id"] for row in listed.json()}
        assert unique not in listed.text

        assert client.get(f"/api/v1/documents/{doc_id}/versions", headers=headers_b).status_code == 404
        assert client.get(f"/api/v1/folders/{folder_id}", headers=headers_b).status_code == 404
        assert client.get(f"/api/v1/conversations/{conversation_id}", headers=headers_b).status_code == 404
        assert client.get(f"/api/v1/connectors/{source_id}/locations", headers=headers_b).status_code in {403, 404}
        assert client.get("/api/v1/roles", headers=headers_b).status_code == 200
        assert role_id not in {row["id"] for row in client.get("/api/v1/roles", headers=headers_b).json()}

        guessed_chat = client.post(
            "/api/v1/chat",
            headers=headers_b,
            json={"question": f"What is {unique}?", "version_id": version_id},
        )
        assert guessed_chat.status_code in {200, 404}
        if guessed_chat.status_code == 200:
            body = guessed_chat.json()
            assert unique.lower() not in body["answer"].lower()
            for cite in body.get("citations") or []:
                assert cite.get("document_id") != doc_id

        stream = client.post(
            "/api/v1/chat/stream",
            headers=headers_b,
            json={"question": "hi", "conversation_id": conversation_id},
        )
        assert stream.status_code == 404

        listed_conn = client.get("/api/v1/connectors", headers=headers_b)
        assert listed_conn.status_code == 200
        assert source_id not in {row["id"] for row in listed_conn.json()}
        assert "encrypted_access_token" not in listed_conn.text
