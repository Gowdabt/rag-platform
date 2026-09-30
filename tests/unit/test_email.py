from __future__ import annotations

import pytest
from app.adapters.providers.email.console import ConsoleEmailProvider, clear_captured_emails, last_captured_email
from app.config.load import load_yaml_layers, parse_settings
from app.config.models import EmailConfig
from app.core.runtime import RuntimeSafetyError, email_config_unsafe, enforce_runtime_safety
from app.domain.ports.email import EmailMessage
from app.email.renderer import UnknownEmailTemplateError, render_template


def test_password_reset_template_renders_without_leaking_missing_keys():
    subject, text, html = render_template(
        "password_reset",
        {
            "applicationName": "RAG Platform",
            "userName": "Ada",
            "tenantName": "Acme",
            "tenantSlug": "acme",
            "resetUrl": "http://localhost:5173/reset?token=abc&slug=acme",
            "expiresIn": "24 hours",
        },
    )
    assert "Ada" in text
    assert "token=abc" in text
    assert "&lt;" not in html
    assert "Reset your RAG Platform password" in subject


def test_template_html_escapes_user_name():
    _subject, _text, html = render_template(
        "user_invitation",
        {
            "applicationName": "RAG Platform",
            "userName": "<script>x</script>",
            "inviterName": "Pat",
            "tenantName": "Acme",
            "tenantSlug": "acme",
            "roleName": "Member",
            "inviteUrl": "http://localhost:5173/invite?token=xyz",
            "expiresIn": "7 days",
            "loginUrl": "http://localhost:5173/",
        },
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_missing_template_data_raises():
    with pytest.raises(UnknownEmailTemplateError):
        render_template("password_reset", {"applicationName": "x"})


def test_console_provider_captures_without_logging_body(caplog):
    import asyncio

    clear_captured_emails()
    provider = ConsoleEmailProvider(EmailConfig())
    message = EmailMessage(
        to="user@example.com",
        subject="Hello",
        text="secret-token-value",
        html="<p>secret-token-value</p>",
    )
    with caplog.at_level("INFO"):
        result = asyncio.run(provider.send(message))
    assert result.ok
    captured = last_captured_email()
    assert captured is not None
    assert captured.text == "secret-token-value"
    assert "secret-token-value" not in caplog.text


def test_production_refuses_console_email(monkeypatch):
    monkeypatch.delenv("RAG_ALLOW_PUBLIC_SIGNUP", raising=False)
    monkeypatch.setenv("RAG_ALLOW_PUBLIC_SIGNUP", "0")
    monkeypatch.setenv("JWT_SECRET", "a" * 40)
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    data = load_yaml_layers("development")
    data["platform"]["environment"] = "production"
    data["http"] = {"cors_origins": ["https://app.example"]}
    settings = parse_settings(data)
    assert email_config_unsafe(settings)
    with pytest.raises(RuntimeSafetyError, match="console"):
        enforce_runtime_safety(settings)
