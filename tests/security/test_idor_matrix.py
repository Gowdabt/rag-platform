from __future__ import annotations

from uuid import uuid4

import pytest
from app.adapters.providers.embeddings.hashing import HashingEmbedding
from app.application.ingestion import IngestionService
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _local_providers(monkeypatch):
    """Keep ACL/IDOR coverage offline (no Ollama)."""
    from app.adapters.providers.llm.extractive import ExtractiveLLM
    from app.application.factory import ProviderFactory

    def _embedder(self):
        return HashingEmbedding(self.settings.embedding, self.ctx)

    original = ProviderFactory.create

    def create(self, kind, name=None, **kwargs):
        if kind == "embedding":
            return HashingEmbedding(kwargs.get("config") or self.settings.embedding, kwargs.get("ctx") or self.ctx)
        if kind == "llm":
            return ExtractiveLLM(kwargs.get("config") or self.settings.llm, kwargs.get("ctx") or self.ctx)
        return original(self, kind, name, **kwargs)

    monkeypatch.setattr(IngestionService, "_embedder", _embedder)
    monkeypatch.setattr(ProviderFactory, "create", create)


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


def _invite_member(client: TestClient, admin_headers: dict, tenant_id: str):
    email = f"idor-{uuid4().hex[:8]}@example.com"
    invited = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={"email": email, "password": "supersecret1", "role": "Member"},
    )
    assert invited.status_code == 200, invited.text
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "supersecret1", "tenant_id": tenant_id},
    )
    assert login.status_code == 200, login.text
    return email, {"Authorization": f"Bearer {login.json()['access_token']}"}, invited.json()["user_id"]


def test_acl_and_idor_matrix_for_core_resources():
    app = create_app()
    with TestClient(app) as client:
        _owner_email, owner, body = _signup(client, prefix="idor-own")
        tenant_id = body["tenant_id"]
        _member_email, member, _user_id = _invite_member(client, owner, tenant_id)
        _other_email, other, _ = _signup(client, prefix="idor-x")

        # Signup owner is Tenant Admin; default admin uploads are tenant-wide — force private for ACL IDOR.
        uploaded = client.post(
            "/api/v1/documents",
            headers=owner,
            files={"file": ("private.md", b"# Owner only\nPRIVATE-DOC-TEXT\n", "text/markdown")},
            data={"visibility": "private"},
        )
        assert uploaded.status_code == 200, uploaded.text
        doc_id = uploaded.json()["document_id"]
        owner_docs = client.get("/api/v1/documents", headers=owner)
        assert owner_docs.status_code == 200
        acl_row = next(row for row in owner_docs.json() if row["id"] == doc_id)
        assert acl_row["acl"]["visibility"] == "private"

        folder = client.post("/api/v1/folders", headers=owner, json={"name": "Private"})
        assert folder.status_code == 200, folder.text
        folder_id = folder.json()["id"]

        chat = client.post("/api/v1/chat", headers=owner, json={"question": "Summarize PRIVATE-DOC-TEXT"})
        assert chat.status_code == 200, chat.text
        conversation_id = chat.json()["conversation_id"]

        connector = client.post(
            "/api/v1/connectors",
            headers=owner,
            json={"connector_type": "local_fs", "name": "Owner FS"},
        )
        assert connector.status_code == 200, connector.text
        source_id = connector.json()["id"]

        role = client.post(
            "/api/v1/roles",
            headers=owner,
            json={"name": f"Hidden-{uuid4().hex[:6]}", "permissions": ["folders.view"]},
        )
        assert role.status_code == 200, role.text
        role_id = role.json()["id"]

        put_ai = client.put("/api/v1/tenant/ai-config", headers=owner, json={"temperature": 0.2})
        assert put_ai.status_code == 200, put_ai.text

        # Intra-tenant member cannot read unshared owner resources (ACL).
        assert client.get(f"/api/v1/documents/{doc_id}/versions", headers=member).status_code == 404
        docs_member = client.get("/api/v1/documents", headers=member)
        assert docs_member.status_code == 200
        assert doc_id not in {row["id"] for row in docs_member.json()}
        member_chat = client.post("/api/v1/chat", headers=member, json={"question": "What is PRIVATE-DOC-TEXT?"})
        assert member_chat.status_code == 200, member_chat.text
        assert "private-doc-text" not in member_chat.json()["answer"].lower()
        for cite in member_chat.json().get("citations") or []:
            assert cite.get("document_id") != doc_id
        assert client.get(f"/api/v1/conversations/{conversation_id}", headers=member).status_code == 404
        assert client.get(f"/api/v1/connectors/{source_id}/locations", headers=member).status_code in {403, 404}
        listed_conn = client.get("/api/v1/connectors", headers=member)
        assert listed_conn.status_code == 200
        assert source_id not in {row["id"] for row in listed_conn.json()}

        # Cross-tenant IDOR is 404 / no leak (not 403 with existence).
        for headers in (member, other):
            assert client.get(f"/api/v1/documents/{doc_id}/versions", headers=headers).status_code == 404
            assert client.post(
                f"/api/v1/documents/{doc_id}/acl",
                headers=headers,
                json={"emails": ["x@example.com"]},
            ).status_code in {403, 404}
            assert client.get(f"/api/v1/folders/{folder_id}", headers=headers).status_code == 404
            assert client.patch(f"/api/v1/folders/{folder_id}", headers=headers, json={"name": "x"}).status_code in {
                403,
                404,
            }
            assert client.get(f"/api/v1/conversations/{conversation_id}", headers=headers).status_code == 404
            assert client.delete(f"/api/v1/conversations/{conversation_id}", headers=headers).status_code in {403, 404}
            assert client.get(f"/api/v1/connectors/{source_id}/health", headers=headers).status_code in {403, 404}
            assert client.delete(f"/api/v1/connectors/{source_id}", headers=headers).status_code in {403, 404}

        other_roles = client.get("/api/v1/roles", headers=other)
        assert other_roles.status_code == 200
        assert role_id not in {row["id"] for row in other_roles.json()}
        assert client.put(
            f"/api/v1/roles/{role_id}",
            headers=other,
            json={"name": "Hacked", "permissions": ["document:read_all"]},
        ).status_code == 404
        other_ai = client.get("/api/v1/tenant/ai-config", headers=other)
        assert other_ai.status_code == 200
        assert other_ai.json().get("temperature") != 0.2

        # Share then revoke: next request loses access (authz epoch / hydrate).
        shared = client.post(
            f"/api/v1/documents/{doc_id}/acl",
            headers=owner,
            json={"emails": [_member_email]},
        )
        assert shared.status_code == 200, shared.text
        visible = client.get(f"/api/v1/documents/{doc_id}/versions", headers=member)
        assert visible.status_code == 200
        revoked = client.post(
            f"/api/v1/documents/{doc_id}/acl",
            headers=owner,
            json={"emails": [], "allowed_users": []},
        )
        assert revoked.status_code == 200, revoked.text
        hidden_again = client.get(f"/api/v1/documents/{doc_id}/versions", headers=member)
        assert hidden_again.status_code == 404
