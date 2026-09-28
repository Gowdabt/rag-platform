import os
from uuid import uuid4

import pytest
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text


def test_deleted_documents_are_not_in_chat_or_citations():
    app = create_app()
    with TestClient(app) as client:
        email = f"del-{uuid4().hex[:8]}@example.com"
        signup = client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "supersecret1", "tenant_name": f"Del{uuid4().hex[:6]}"},
        )
        if signup.status_code >= 500:
            pytest.skip("database unavailable")
        headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
        marker = f"GONE-{uuid4().hex[:8]}"
        uploaded = client.post(
            "/api/v1/documents",
            headers=headers,
            files={"file": ("gone.md", f"# Gone\n{marker} must disappear.\n".encode(), "text/markdown")},
        )
        assert uploaded.status_code == 200, uploaded.text
        doc_id = uploaded.json()["document_id"]
        before = client.post("/api/v1/chat", headers=headers, json={"question": f"What is {marker}?"})
        assert before.status_code == 200, before.text

        url = os.environ.get("DATABASE_URL_SYNC", "postgresql+psycopg://rag:rag@localhost:5432/rag")
        engine = create_engine(url)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE documents SET external_status = 'deleted_externally' WHERE id = :id"),
                    {"id": doc_id},
                )
        finally:
            engine.dispose()

        listed = client.get("/api/v1/documents", headers=headers)
        assert listed.status_code == 200
        assert doc_id not in {row["id"] for row in listed.json()}
        after = client.post("/api/v1/chat", headers=headers, json={"question": f"What is {marker}?"})
        assert after.status_code == 200, after.text
        assert marker.lower() not in after.json()["answer"].lower()
        for cite in after.json().get("citations") or []:
            assert cite.get("document_id") != doc_id
        versions = client.get(f"/api/v1/documents/{doc_id}/versions", headers=headers)
        assert versions.status_code == 404
