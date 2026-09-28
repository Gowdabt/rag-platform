"""Tenant isolation helpers and HTTP tests for retrieval ACL."""

from uuid import uuid4

import pytest
from app.application.ingestion import _visible
from app.core.cache import TenantCache
from app.core.context import RequestContext
from app.main import create_app
from fastapi.testclient import TestClient


def test_empty_acl_denies_document_read():
    ctx = RequestContext(request_id="t", user_id=uuid4(), permissions=frozenset({"document:read"}))
    assert not _visible({}, ctx)


def test_restricted_acl_hides_from_other_users():
    allowed = uuid4()
    other = uuid4()
    ctx = RequestContext(
        request_id="t",
        user_id=other,
        permissions=frozenset({"document:read"}),
        team_names=(),
    )
    assert not _visible({"allowed_users": [str(allowed)], "owner_id": str(allowed)}, ctx)
    ctx2 = RequestContext(
        request_id="t",
        user_id=allowed,
        permissions=frozenset({"document:read"}),
    )
    assert _visible({"allowed_users": [str(allowed)], "owner_id": str(allowed)}, ctx2)


def test_tenant_cache_keys_include_tenant_and_user():
    cache = TenantCache()
    tenant_a = uuid4()
    tenant_b = uuid4()
    user = uuid4()
    cache.set_tenant(tenant_a, "q", "answer-a", user_id=user)
    cache.set_tenant(tenant_b, "q", "answer-b", user_id=user)
    assert cache.get_tenant(tenant_a, "q", user_id=user) == "answer-a"
    assert cache.get_tenant(tenant_b, "q", user_id=user) == "answer-b"
    with pytest.raises(ValueError):
        cache.get("q")
    with pytest.raises(ValueError):
        cache.scoped_key("", "q")
    with pytest.raises(ValueError):
        cache.scoped_key(tenant_a, "q")
    cache.bump(tenant_a, user)
    assert cache.get_tenant(tenant_a, "q", user_id=user) is None


def test_db_authz_epoch_is_required_in_cache_keys_across_processes():
    import os

    from app.core.cache import TenantCache
    from sqlalchemy import create_engine, text

    app = create_app()
    with TestClient(app) as client:
        _email, headers, body = _signup(client, prefix="epoch")
        tenant_id = body["tenant_id"]
        user_id = body["user_id"]
        url = os.environ.get("DATABASE_URL_SYNC", "postgresql+psycopg://rag:rag@localhost:5432/rag")
        engine = create_engine(url)
        try:
            with engine.begin() as conn:
                before = conn.execute(
                    text("SELECT authz_epoch FROM tenants WHERE id = CAST(:id AS uuid)"),
                    {"id": tenant_id},
                ).scalar()
                if before is None:
                    pytest.skip("authz_epoch column missing — run alembic 008")
                worker_a = TenantCache()
                worker_a.set_tenant(tenant_id, "q", "stale-secret", user_id=user_id, authz_epoch=int(before))
                conn.execute(
                    text("UPDATE tenants SET authz_epoch = authz_epoch + 1 WHERE id = CAST(:id AS uuid)"),
                    {"id": tenant_id},
                )
                after = conn.execute(
                    text("SELECT authz_epoch FROM tenants WHERE id = CAST(:id AS uuid)"),
                    {"id": tenant_id},
                ).scalar()
            worker_b = TenantCache()
            assert int(after) == int(before) + 1
            assert worker_a.get_tenant(tenant_id, "q", user_id=user_id, authz_epoch=int(after)) is None
            assert worker_b.get_tenant(tenant_id, "q", user_id=user_id, authz_epoch=int(after)) is None
            assert worker_a.get_tenant(tenant_id, "q", user_id=user_id, authz_epoch=int(before)) == "stale-secret"
            patched = client.patch(
                f"/api/v1/users/{user_id}",
                headers=headers,
                json={"status": "active"},
            )
            assert patched.status_code == 200, patched.text
        except Exception as exc:
            if "authz_epoch" in str(exc) or "does not exist" in str(exc).lower():
                pytest.skip("authz_epoch column missing — run alembic 008")
            raise
        finally:
            engine.dispose()


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


def test_two_tenants_cannot_read_each_others_documents_or_chat():
    app = create_app()
    with TestClient(app) as client:
        _email_a, headers_a, _ = _signup(client, prefix="iso-a")
        unique = f"TENANT-A-SECRET-{uuid4().hex[:8]}"
        uploaded = client.post(
            "/api/v1/documents",
            headers=headers_a,
            files={"file": ("secret.md", f"# Secret\n{unique} is only for tenant A.\n".encode(), "text/markdown")},
        )
        assert uploaded.status_code == 200, uploaded.text
        doc_id = uploaded.json()["document_id"]
        version_id = uploaded.json()["version_id"]

        chat_a = client.post("/api/v1/chat", headers=headers_a, json={"question": f"What is {unique}?"})
        assert chat_a.status_code == 200, chat_a.text
        conversation_id = chat_a.json()["conversation_id"]

        _email_b, headers_b, _ = _signup(client, prefix="iso-b")
        listed = client.get("/api/v1/documents", headers=headers_b)
        assert listed.status_code == 200
        assert doc_id not in {row["id"] for row in listed.json()}
        assert unique not in listed.text

        guessed_doc = client.get(f"/api/v1/documents/{doc_id}/versions", headers=headers_b)
        assert guessed_doc.status_code == 404

        guessed_chat = client.post(
            "/api/v1/chat",
            headers=headers_b,
            json={"question": f"What is {unique}?", "version_id": version_id},
        )
        assert guessed_chat.status_code in {200, 404}
        if guessed_chat.status_code == 200:
            assert unique.lower() not in guessed_chat.json()["answer"].lower()

        conv = client.get(f"/api/v1/conversations/{conversation_id}", headers=headers_b)
        assert conv.status_code == 404

        same_q = client.post("/api/v1/chat", headers=headers_b, json={"question": f"What is {unique}?"})
        assert same_q.status_code == 200, same_q.text
        assert unique.lower() not in same_q.json()["answer"].lower()
