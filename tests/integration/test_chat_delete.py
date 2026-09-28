from uuid import uuid4

import pytest
from app.main import create_app
from fastapi.testclient import TestClient


def test_user_can_delete_one_conversation_and_clear_all():
    app = create_app()
    with TestClient(app) as client:
        email = f"chat-{uuid4().hex[:8]}@example.com"
        signup = client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "supersecret1", "tenant_name": f"Chat{uuid4().hex[:6]}"},
        )
        if signup.status_code >= 500:
            pytest.skip("database unavailable")
        assert signup.status_code == 200, signup.text
        headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}

        first = client.post("/api/v1/chat", headers=headers, json={"question": "how many docs we have"})
        assert first.status_code == 200, first.text
        first_id = first.json()["conversation_id"]

        second = client.post("/api/v1/chat", headers=headers, json={"question": "list documents"})
        assert second.status_code == 200, second.text
        second_id = second.json()["conversation_id"]
        assert first_id != second_id

        listed = client.get("/api/v1/conversations", headers=headers)
        assert listed.status_code == 200
        ids = {row["id"] for row in listed.json()}
        assert first_id in ids and second_id in ids

        deleted = client.delete(f"/api/v1/conversations/{first_id}", headers=headers)
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["status"] == "deleted"

        after = client.get("/api/v1/conversations", headers=headers)
        remaining = {row["id"] for row in after.json()}
        assert first_id not in remaining
        assert second_id in remaining
        missing = client.get(f"/api/v1/conversations/{first_id}", headers=headers)
        assert missing.status_code == 404

        cleared = client.delete("/api/v1/conversations", headers=headers)
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["deleted"] >= 1
        empty = client.get("/api/v1/conversations", headers=headers)
        assert empty.json() == []
