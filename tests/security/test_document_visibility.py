"""Upload visibility control: role grants, defaults, and cross-tenant denial."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.adapters.providers.embeddings.hashing import HashingEmbedding
from app.application.authz import default_upload_acl, resolve_upload_acl
from app.application.ingestion import IngestionService
from app.core.context import RequestContext
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _hashing_embeddings(monkeypatch):
    """Avoid depending on Ollama for visibility ACL coverage."""

    def _embedder(self):
        return HashingEmbedding(self.settings.embedding, self.ctx)

    monkeypatch.setattr(IngestionService, "_embedder", _embedder)
    # Chat is not asserted here; keep retrieval-free paths offline.


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


def _login(client: TestClient, email: str, tenant_id: str):
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "supersecret1", "tenant_id": tenant_id},
    )
    assert login.status_code == 200, login.text
    return _headers(login.json()["access_token"])


def _invite(client: TestClient, admin: dict, email: str, role: str) -> None:
    invited = client.post(
        "/api/v1/users",
        headers=admin,
        json={"email": email, "password": "supersecret1", "role": role},
    )
    assert invited.status_code == 200, invited.text


def _titles(client: TestClient, headers: dict) -> set[str]:
    listed = client.get("/api/v1/documents", headers=headers)
    assert listed.status_code == 200, listed.text
    return {row["title"] for row in listed.json()}


def _upload(
    client: TestClient,
    headers: dict,
    *,
    name: str,
    body: bytes = b"hello visibility\n",
    visibility: str | None = None,
    allowed_roles: str | None = None,
) -> dict:
    data: dict = {}
    if visibility is not None:
        data["visibility"] = visibility
    if allowed_roles is not None:
        data["allowed_roles"] = allowed_roles
    response = client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": (name, body, "text/plain")},
        data=data,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_default_upload_acl_unit():
    member_id = uuid4()
    admin_id = uuid4()
    member_ctx = RequestContext(
        request_id="t",
        user_id=member_id,
        role_names=("Member",),
        permissions=frozenset({"document:read", "document:write"}),
    )
    admin_ctx = RequestContext(
        request_id="t",
        user_id=admin_id,
        role_names=("Tenant Admin",),
        permissions=frozenset({"document:read", "document:write"}),
    )
    assert default_upload_acl(member_ctx)["visibility"] == "private"
    assert default_upload_acl(admin_ctx)["visibility"] == "tenant"
    granted = resolve_upload_acl(member_ctx, allowed_roles=["Viewer", "Tenant Admin"])
    assert granted["visibility"] == "private"
    assert granted["allowed_roles"] == ["Viewer", "Tenant Admin"]


def test_member_upload_hidden_from_viewer_and_admin_unless_granted():
    app = create_app()
    with TestClient(app) as client:
        _admin_email, admin, body = _signup(client, prefix="vis-admin")
        tenant_id = body["tenant_id"]
        member_email = f"mem-{uuid4().hex[:8]}@example.com"
        viewer_email = f"view-{uuid4().hex[:8]}@example.com"
        _invite(client, admin, member_email, "Member")
        _invite(client, admin, viewer_email, "Viewer")
        member = _login(client, member_email, tenant_id)
        viewer = _login(client, viewer_email, tenant_id)

        private_name = f"private-{uuid4().hex[:6]}.txt"
        _upload(client, member, name=private_name, visibility="private")

        assert private_name in _titles(client, member)
        assert private_name not in _titles(client, viewer)
        assert private_name not in _titles(client, admin)

        me_admin = client.get("/api/v1/auth/me", headers=admin).json()
        assert "document:read_all" not in (me_admin.get("permissions") or [])

        shared_name = f"shared-{uuid4().hex[:6]}.txt"
        uploaded = _upload(
            client,
            member,
            name=shared_name,
            visibility="private",
            allowed_roles='["Viewer","Tenant Admin"]',
        )
        assert shared_name in _titles(client, viewer)
        assert shared_name in _titles(client, admin)
        versions = client.get(f"/api/v1/documents/{uploaded['document_id']}/versions", headers=viewer)
        assert versions.status_code == 200
        assert private_name not in _titles(client, viewer)


def test_tenant_admin_upload_visible_to_member_and_viewer_by_default():
    app = create_app()
    with TestClient(app) as client:
        _admin_email, admin, body = _signup(client, prefix="vis-ta")
        tenant_id = body["tenant_id"]
        member_email = f"mem-{uuid4().hex[:8]}@example.com"
        viewer_email = f"view-{uuid4().hex[:8]}@example.com"
        _invite(client, admin, member_email, "Member")
        _invite(client, admin, viewer_email, "Viewer")
        member = _login(client, member_email, tenant_id)
        viewer = _login(client, viewer_email, tenant_id)

        name = f"admin-doc-{uuid4().hex[:6]}.txt"
        uploaded = _upload(client, admin, name=name, body=b"tenant wide admin note\n")
        docs = client.get("/api/v1/documents", headers=admin)
        assert docs.status_code == 200
        row = next(r for r in docs.json() if r["title"] == name)
        assert row["acl"]["visibility"] == "tenant"

        assert name in _titles(client, member)
        assert name in _titles(client, viewer)
        assert (
            client.get(f"/api/v1/documents/{uploaded['document_id']}/versions", headers=member).status_code
            == 200
        )

        narrowed = client.post(
            f"/api/v1/documents/{uploaded['document_id']}/acl",
            headers=admin,
            json={"visibility": "private", "allowed_roles": []},
        )
        assert narrowed.status_code == 200, narrowed.text
        assert name not in _titles(client, member)
        assert name not in _titles(client, viewer)


def test_document_visibility_denied_across_tenants():
    app = create_app()
    with TestClient(app) as client:
        _a_email, admin_a, _body_a = _signup(client, prefix="vis-a")
        _b_email, admin_b, _body_b = _signup(client, prefix="vis-b")
        name = f"cross-{uuid4().hex[:6]}.txt"
        uploaded = _upload(client, admin_a, name=name)
        assert name not in _titles(client, admin_b)
        denied = client.get(
            f"/api/v1/documents/{uploaded['document_id']}/versions",
            headers=admin_b,
        )
        assert denied.status_code == 404
        denied_acl = client.post(
            f"/api/v1/documents/{uploaded['document_id']}/acl",
            headers=admin_b,
            json={"visibility": "private", "allowed_roles": []},
        )
        assert denied_acl.status_code == 404


def test_granted_member_cannot_change_visibility_owner_and_admin_can():
    """Tenant Admin share is read access. The member cannot retarget visibility."""
    app = create_app()
    with TestClient(app) as client:
        _admin_email, admin, body = _signup(client, prefix="vis-share")
        tenant_id = body["tenant_id"]
        member_email = f"mem-{uuid4().hex[:8]}@example.com"
        viewer_email = f"view-{uuid4().hex[:8]}@example.com"
        _invite(client, admin, member_email, "Member")
        _invite(client, admin, viewer_email, "Viewer")
        member = _login(client, member_email, tenant_id)
        viewer = _login(client, viewer_email, tenant_id)

        shared_name = f"admin-shared-{uuid4().hex[:6]}.txt"
        uploaded = _upload(
            client,
            admin,
            name=shared_name,
            visibility="private",
            allowed_roles='["Member"]',
        )
        doc_id = uploaded["document_id"]
        assert shared_name in _titles(client, member)
        assert client.get(f"/api/v1/documents/{doc_id}/versions", headers=member).status_code == 200

        denied = client.post(
            f"/api/v1/documents/{doc_id}/acl",
            headers=member,
            json={"visibility": "tenant", "allowed_roles": []},
        )
        assert denied.status_code == 403, denied.text
        listed = client.get("/api/v1/documents", headers=admin)
        assert listed.status_code == 200
        row = next(item for item in listed.json() if item["id"] == doc_id)
        assert row["acl"]["visibility"] == "private"
        assert "Member" in (row["acl"].get("allowed_roles") or [])

        changed = client.post(
            f"/api/v1/documents/{doc_id}/acl",
            headers=admin,
            json={"visibility": "tenant", "allowed_roles": []},
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["acl"]["visibility"] == "tenant"
        assert shared_name in _titles(client, viewer)
        viewer_denied = client.post(
            f"/api/v1/documents/{doc_id}/acl",
            headers=viewer,
            json={"visibility": "private", "allowed_roles": []},
        )
        assert viewer_denied.status_code == 403, viewer_denied.text

        own_name = f"member-own-{uuid4().hex[:6]}.txt"
        own = _upload(client, member, name=own_name, visibility="private")
        own_changed = client.post(
            f"/api/v1/documents/{own['document_id']}/acl",
            headers=member,
            json={"visibility": "private", "allowed_roles": ["Viewer"]},
        )
        assert own_changed.status_code == 200, own_changed.text
        assert own_changed.json()["acl"]["visibility"] == "private"
        assert own_changed.json()["acl"]["allowed_roles"] == ["Viewer"]
        assert own_name not in _titles(client, admin)
        # Tenant Admin still has no document:read_all, but may change ACL on a member-private doc.
        admin_me = client.get("/api/v1/auth/me", headers=admin)
        assert admin_me.status_code == 200
        assert "document:read_all" not in (admin_me.json().get("permissions") or [])
        admin_acl = client.post(
            f"/api/v1/documents/{own['document_id']}/acl",
            headers=admin,
            json={"visibility": "private", "allowed_roles": ["Viewer"]},
        )
        assert admin_acl.status_code == 200, admin_acl.text
