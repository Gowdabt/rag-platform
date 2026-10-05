from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from app.application.authz import document_acl_sql
from app.config.load import load_yaml_layers, parse_settings
from app.core.rate_limit import RateLimitMiddleware
from app.core.runtime import RuntimeSafetyError, enforce_runtime_safety, jwt_secret_is_unsafe
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


def test_repo_invariants_no_raw_token_logs_or_query_only_cache():
    root = Path(__file__).resolve().parents[2]
    identity = (root / "backend/app/application/identity.py").read_text(encoding="utf-8")
    assert "token=token" not in identity
    cache = (root / "backend/app/core/cache.py").read_text(encoding="utf-8")
    assert "authz epoch" in cache
    fts = (root / "backend/app/adapters/providers/sparse_indexes/postgres_fts.py").read_text(encoding="utf-8")
    vec = (root / "backend/app/adapters/providers/vectorstores/pgvector_store.py").read_text(encoding="utf-8")
    chat = (root / "backend/app/application/chat.py").read_text(encoding="utf-8")
    assert document_acl_sql("d").strip()
    assert "document_acl_sql" in fts
    assert "document_acl_sql" in vec
    assert "document_acl_sql" in chat
    assert "authorized_document_ids" in chat
    docs_api = (root / "backend/app/api/v1/documents.py").read_text(encoding="utf-8")
    folders_api = (root / "backend/app/api/v1/folders.py").read_text(encoding="utf-8")
    connectors_api = (root / "backend/app/api/v1/connectors.py").read_text(encoding="utf-8")
    assert "tenant_id" not in docs_api
    assert "tenant_id" not in folders_api
    assert "body.tenant_id" not in connectors_api


def test_health_live_ready_and_security_headers():
    with TestClient(create_app()) as client:
        live = client.get("/api/v1/health/live")
        assert live.status_code == 200
        assert live.json()["status"] == "ok"
        ready = client.get("/api/v1/health/ready")
        assert ready.status_code in {200, 503}
        assert "password" not in ready.text.lower()
        assert "jwt" not in ready.text.lower()
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert "jwt" not in health.text.lower()
        assert "base" not in health.json().get("ollama", {})
        assert health.headers.get("x-content-type-options") == "nosniff"
        assert health.headers.get("x-frame-options") == "DENY"
        assert "no-store" in (health.headers.get("cache-control") or "")
        origin = client.get("/api/v1/health/live", headers={"Origin": "https://evil.example"})
        acao = origin.headers.get("access-control-allow-origin")
        assert acao != "*"
        allowed = client.get("/api/v1/health/live", headers={"Origin": "http://localhost:5173"})
        assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_production_runtime_safety(monkeypatch):
    monkeypatch.delenv("RAG_ALLOW_PUBLIC_SIGNUP", raising=False)
    monkeypatch.setenv("RAG_ALLOW_PUBLIC_SIGNUP", "0")
    monkeypatch.setenv("JWT_SECRET", "a" * 40)
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    data = load_yaml_layers("development")
    data["platform"]["environment"] = "production"
    data["http"] = {"cors_origins": ["*"]}
    data["email"] = {
        "provider": "smtp",
        "from_address": "no-reply@example.com",
        "public_app_url": "https://app.example",
        "smtp_host": "smtp.example.com",
    }
    settings = parse_settings(data)
    with pytest.raises(RuntimeSafetyError):
        enforce_runtime_safety(settings)
    data["http"] = {"cors_origins": ["https://app.example"]}
    settings = parse_settings(data)
    monkeypatch.setenv("RAG_ALLOW_PUBLIC_SIGNUP", "1")
    with pytest.raises(RuntimeSafetyError):
        enforce_runtime_safety(settings)
    assert jwt_secret_is_unsafe("change-me-to-a-long-random-string")


def test_login_enumeration_is_generic():
    app = create_app()
    with TestClient(app) as client:
        email, _headers, body = _signup(client, prefix="enum")
        missing = client.post(
            "/api/v1/auth/login",
            json={"email": f"nope-{uuid4().hex[:8]}@example.com", "password": "supersecret1", "tenant_slug": "missing"},
        )
        wrong = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "definitely-wrong", "tenant_id": body["tenant_id"]},
        )
        assert missing.status_code == 401
        assert wrong.status_code == 401
        assert missing.json()["detail"] == wrong.json()["detail"]
        forgot_known = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": email, "tenant_slug": "unknown-slug"},
        )
        forgot_unknown = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": f"nope-{uuid4().hex[:8]}@example.com", "tenant_slug": "unknown-slug"},
        )
        assert forgot_known.status_code == 200
        assert forgot_unknown.status_code == 200
        assert forgot_known.json()["ok"] is True
        assert forgot_unknown.json()["ok"] is True


def test_disabled_user_jwt_rejected_immediately():
    app = create_app()
    with TestClient(app) as client:
        _admin, admin_headers, body = _signup(client, prefix="jwt-dis")
        member = f"jwt-dis-{uuid4().hex[:8]}@example.com"
        invited = client.post(
            "/api/v1/users",
            headers=admin_headers,
            json={"email": member, "password": "supersecret1", "role": "Member"},
        )
        assert invited.status_code == 200, invited.text
        login = client.post(
            "/api/v1/auth/login",
            json={"email": member, "password": "supersecret1", "tenant_id": body["tenant_id"]},
        )
        assert login.status_code == 200, login.text
        member_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        me = client.get("/api/v1/auth/me", headers=member_headers)
        assert me.status_code == 200
        patched = client.patch(
            f"/api/v1/users/{invited.json()['user_id']}",
            headers=admin_headers,
            json={"status": "disabled"},
        )
        assert patched.status_code == 200, patched.text
        denied = client.get("/api/v1/auth/me", headers=member_headers)
        assert denied.status_code in {401, 403}


def test_role_revoke_takes_effect_on_next_request():
    app = create_app()
    with TestClient(app) as client:
        _admin, admin_headers, body = _signup(client, prefix="role-rev")
        created = client.post(
            "/api/v1/roles",
            headers=admin_headers,
            json={"name": f"NoDocs-{uuid4().hex[:6]}", "permissions": ["folders.view"]},
        )
        assert created.status_code == 200, created.text
        member = f"role-rev-{uuid4().hex[:8]}@example.com"
        invited = client.post(
            "/api/v1/users",
            headers=admin_headers,
            json={"email": member, "password": "supersecret1", "role": "Member"},
        )
        assert invited.status_code == 200, invited.text
        login = client.post(
            "/api/v1/auth/login",
            json={"email": member, "password": "supersecret1", "tenant_id": body["tenant_id"]},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        allowed = client.get("/api/v1/documents", headers=headers)
        assert allowed.status_code == 200
        patched = client.patch(
            f"/api/v1/users/{invited.json()['user_id']}",
            headers=admin_headers,
            json={"role_ids": [created.json()["id"]]},
        )
        assert patched.status_code == 200, patched.text
        denied = client.get("/api/v1/documents", headers=headers)
        assert denied.status_code == 403
        chat = client.post("/api/v1/chat", headers=headers, json={"question": "hello"})
        assert chat.status_code == 403


def test_refresh_rotation_and_pagination_bounds():
    app = create_app()
    with TestClient(app) as client:
        _email, headers, body = _signup(client, prefix="rot")
        refresh = body["refresh_token"]
        rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        assert rotated.status_code == 200, rotated.text
        reused = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        assert reused.status_code == 401
        oversize = client.get("/api/v1/documents?limit=5000", headers=headers)
        assert oversize.status_code == 422
        ok = client.get("/api/v1/documents?limit=1&offset=0", headers=headers)
        assert ok.status_code == 200
        assert isinstance(ok.json(), list)


def test_auth_rate_limit_tighter_than_general(monkeypatch):
    monkeypatch.setenv("RAG_AUTH_RATE_LIMIT", "3")
    monkeypatch.setenv("RAG_AUTH_RATE_WINDOW", "60")
    app = create_app()
    with TestClient(app) as client:
        payload = {"email": "rate@example.com", "password": "supersecret1", "tenant_slug": "none"}
        codes = [client.post("/api/v1/auth/login", json=payload).status_code for _ in range(5)]
        assert 429 in codes


def test_ingestion_job_revalidates_tenant():
    import inspect

    from app.application.ingestion import IngestionService
    from app.application.jobs import run_ingestion_job
    from app.application.scheduler import run_due_syncs

    src = inspect.getsource(IngestionService.process_job)
    assert "job.tenant_id != self.ctx.tenant_id" in src
    assert "document.tenant_id != self.ctx.tenant_id" in src
    assert "Source missing" in src
    job_src = inspect.getsource(run_ingestion_job)
    assert "hydrate_context" in job_src
    assert "Owning user is not active" in job_src
    assert "Tenant is not active" in job_src
    sched = inspect.getsource(run_due_syncs)
    assert "hydrate_context" in sched
    assert "skip_permission=True" not in sched
    assert "owner.status" in sched


def test_logout_invalidates_refresh_token():
    app = create_app()
    with TestClient(app) as client:
        _email, headers, body = _signup(client, prefix="logout")
        refresh = body["refresh_token"]
        logged_out = client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
        assert logged_out.status_code == 200, logged_out.text
        reused = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        assert reused.status_code == 401
        me = client.get("/api/v1/auth/me", headers=headers)
        assert me.status_code in {200, 401}


def test_sql_list_methods_use_bounded_limit():
    import inspect

    from app.application.connectors import ConnectorService
    from app.application.identity import IdentityService
    from app.application.ingestion import IngestionService

    for method in (
        IdentityService.list_workspaces,
        IdentityService.list_teams,
        IdentityService.list_tenants,
        IdentityService.list_platform_tenants,
        ConnectorService.list_subscriptions,
        ConnectorService.list_sources,
        IngestionService.list_documents,
    ):
        src = inspect.getsource(method)
        assert ".limit(" in src or "LIMIT :" in src or "clip_limit" in src
        assert "[start : start" not in src
        assert "out[start:stop]" not in src


def test_pagination_cannot_cross_tenants():
    app = create_app()
    with TestClient(app) as client:
        _email_a, headers_a, _ = _signup(client, prefix="page-a")
        extra = client.post("/api/v1/workspaces", headers=headers_a, json={"name": f"Extra-{uuid4().hex[:6]}"})
        assert extra.status_code == 200, extra.text
        team = client.post("/api/v1/teams", headers=headers_a, json={"name": f"Team-{uuid4().hex[:6]}"})
        assert team.status_code == 200, team.text
        a_workspaces = {row["id"] for row in client.get("/api/v1/workspaces?limit=100&offset=0", headers=headers_a).json()}
        a_teams = {row["id"] for row in client.get("/api/v1/teams?limit=100&offset=0", headers=headers_a).json()}
        _email_b, headers_b, _ = _signup(client, prefix="page-b")
        b_workspaces = client.get("/api/v1/workspaces?limit=100&offset=0", headers=headers_b)
        b_teams = client.get("/api/v1/teams?limit=100&offset=0", headers=headers_b)
        assert b_workspaces.status_code == 200
        assert b_teams.status_code == 200
        assert a_workspaces.isdisjoint({row["id"] for row in b_workspaces.json()})
        assert a_teams.isdisjoint({row["id"] for row in b_teams.json()})
        overflow = client.get("/api/v1/workspaces?limit=5000", headers=headers_b)
        assert overflow.status_code == 422


def test_html_in_filename_is_stripped_from_document_list():
    app = create_app()
    with TestClient(app) as client:
        _email, headers, _ = _signup(client, prefix="xss")
        uploaded = client.post(
            "/api/v1/documents",
            headers=headers,
            files={"file": ("<img src=x onerror=alert(1)>.md", b"# Title\nplain\n", "text/markdown")},
        )
        assert uploaded.status_code == 200, uploaded.text
        listed = client.get("/api/v1/documents", headers=headers)
        assert listed.status_code == 200
        blob = listed.text
        assert "<img" not in blob
        assert "onerror=" not in blob


def test_rate_limit_middleware_defaults_are_tight(monkeypatch):
    monkeypatch.setenv("RAG_AUTH_RATE_LIMIT", "10")
    monkeypatch.setenv("RAG_AUTH_RATE_WINDOW", "60")
    mw = RateLimitMiddleware(lambda: None, limit=180, window_seconds=60)
    assert mw.auth_limit == 10
    assert mw.auth_window == 60
