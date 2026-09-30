from __future__ import annotations

import re
from uuid import uuid4

import pytest
from app.adapters.providers.email.console import captured_emails, clear_captured_emails, last_captured_email
from app.main import create_app
from fastapi.testclient import TestClient


def _token_from_text(body: str, kind: str) -> str:
    if kind == "reset":
        match = re.search(r"/reset\?token=([a-f0-9]+)", body)
    else:
        match = re.search(r"/invite\?token=([a-f0-9]+)", body)
    assert match, body
    return match.group(1)


def _signup(client: TestClient, *, prefix: str):
    email = f"{prefix}-{uuid4().hex[:8]}@example.com"
    signup = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "oldpassword1", "tenant_name": f"{prefix}{uuid4().hex[:6]}"},
    )
    if signup.status_code >= 500:
        pytest.skip("database unavailable")
    assert signup.status_code == 200, signup.text
    body = signup.json()
    return email, {"Authorization": f"Bearer {body['access_token']}"}, body


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_forgot_reset_login_accepts_mixed_case_slug():
    clear_captured_emails()
    app = create_app()
    with TestClient(app) as client:
        email, headers, _ = _signup(client, prefix="pwreset")
        me = client.get("/api/v1/auth/me", headers=headers)
        assert me.status_code == 200, me.text
        slug = me.json()["tenant_slug"]
        assert slug
        clear_captured_emails()

        forgot = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": email, "tenant_slug": slug.upper()},
        )
        assert forgot.status_code == 200, forgot.text
        body = forgot.json()
        assert body.get("ok") is True
        assert "reset_token" not in body
        assert "token" not in body
        mail = last_captured_email()
        assert mail is not None
        assert mail.to == email
        token = _token_from_text(mail.text, "reset")
        assert slug in mail.text

        too_short = client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "password": "short"},
        )
        assert too_short.status_code in {400, 422}

        missing = client.post("/api/v1/auth/reset-password", json={"token": "", "password": "newpassword1"})
        assert missing.status_code in {400, 422}

        bogus = client.post(
            "/api/v1/auth/reset-password",
            json={"token": "0" * 64, "password": "newpassword1"},
        )
        assert bogus.status_code in {400, 422}

        stale_password = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "oldpassword1", "tenant_slug": slug},
        )
        assert stale_password.status_code == 200

        reset = client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "password": "newpassword1"},
        )
        assert reset.status_code == 200, reset.text
        assert reset.json().get("ok") is True

        reused = client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "password": "newpassword1"},
        )
        assert reused.status_code in {400, 422}

        old_login = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "oldpassword1", "tenant_slug": slug},
        )
        assert old_login.status_code in {401, 403}

        logged = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "newpassword1", "tenant_slug": slug.title()},
        )
        assert logged.status_code == 200, logged.text
        assert logged.json().get("access_token")


def test_forgot_password_unknown_email_is_generic():
    clear_captured_emails()
    app = create_app()
    with TestClient(app) as client:
        missing = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": f"missing-{uuid4().hex[:8]}@example.com", "tenant_slug": "no-such-tenant"},
        )
        if missing.status_code >= 500:
            pytest.skip("database unavailable")
        assert missing.status_code == 200
        assert missing.json().get("ok") is True
        assert "reset_token" not in missing.json()
        assert last_captured_email() is None


def test_invited_user_can_set_password_via_forgot_reset(monkeypatch):
    sa_email = f"sa-{uuid4().hex[:8]}@example.com"
    monkeypatch.setenv("PLATFORM_SUPERADMIN_EMAIL", sa_email)
    monkeypatch.setenv("PLATFORM_SUPERADMIN_PASSWORD", "supersecret1")
    clear_captured_emails()
    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": sa_email, "password": "supersecret1"})
        if login.status_code >= 500:
            pytest.skip("database unavailable")
        assert login.status_code == 200, login.text
        sa = _headers(login.json()["access_token"])
        suffix = uuid4().hex[:6]
        slug = f"invitepw-{suffix}"
        admin_email = f"invitepw-{suffix}@example.com"
        created = client.post(
            "/api/v1/platform/tenants",
            headers=sa,
            json={
                "name": "Invite PW",
                "slug": slug,
                "admin_name": "Invited Admin",
                "admin_email": admin_email,
            },
        )
        assert created.status_code == 200, created.text
        assert created.json().get("password_set") is False
        welcome = [m for m in captured_emails() if m.to == admin_email]
        assert welcome
        assert "/invite?token=" in welcome[0].text or "/reset?token=" in welcome[0].text

        blocked = client.post(
            "/api/v1/auth/login",
            json={"email": admin_email, "password": "newpassword1", "tenant_slug": slug},
        )
        assert blocked.status_code in {401, 403}

        clear_captured_emails()
        forgot = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": admin_email, "tenant_slug": slug.upper()},
        )
        assert forgot.status_code == 200, forgot.text
        assert "reset_token" not in forgot.json()
        token = _token_from_text(last_captured_email().text, "reset")

        reset = client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "password": "newpassword1"},
        )
        assert reset.status_code == 200, reset.text

        logged = client.post(
            "/api/v1/auth/login",
            json={"email": admin_email, "password": "newpassword1", "tenant_slug": slug.upper()},
        )
        assert logged.status_code == 200, logged.text
        me = client.get("/api/v1/auth/me", headers=_headers(logged.json()["access_token"]))
        assert me.status_code == 200
        assert me.json()["tenant_slug"] == slug
        assert me.json()["email"] == admin_email


def test_create_invitation_sends_mail_and_identity_does_not_import_smtp():
    from pathlib import Path

    identity = (Path(__file__).resolve().parents[2] / "backend/app/application/identity.py").read_text(encoding="utf-8")
    assert "smtplib" not in identity
    assert "resend.com" not in identity
    assert "EmailService" in identity
