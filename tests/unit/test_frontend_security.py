from pathlib import Path


def test_frontend_does_not_store_provider_secrets_and_logout_clears_tokens():
    root = Path(__file__).resolve().parents[2]
    client = (root / "frontend/src/api/client.ts").read_text(encoding="utf-8")
    app = (root / "frontend/src/App.tsx").read_text(encoding="utf-8")
    assert "localStorage.setItem(\"access_token\"" in app or "localStorage.setItem('access_token'" in app
    assert "removeItem(\"access_token\")" in app or "removeItem('access_token')" in app
    assert "removeItem(\"refresh_token\")" in app or "removeItem('refresh_token')" in app
    assert "/api/v1/auth/logout" in client
    assert "JWT_SECRET" not in client
    assert "OPENAI_API_KEY" not in client
    assert "JWT_SECRET" not in app
    assert "OPENAI_API_KEY" not in app
    # OAuth API payloads may include a client_secret field name; it must not land in UI state.
    assert "localStorage" in app
    assert "client_secret" not in app
    chat = (root / "frontend/src/pages/ChatPage.tsx").read_text(encoding="utf-8")
    docs = (root / "frontend/src/pages/DocumentsPage.tsx").read_text(encoding="utf-8")
    folders = (root / "frontend/src/pages/FoldersPage.tsx").read_text(encoding="utf-8")
    untrusted = (root / "frontend/src/security/untrusted.ts").read_text(encoding="utf-8")
    for source in (chat, docs, folders, app, client):
        assert "dangerouslySetInnerHTML" not in source
        assert ".innerHTML" not in source
    assert "untrustedText" in chat
    assert "untrustedText" in docs
    assert "untrustedText" in folders
    assert "replace(/<[^>]*>/g" in untrusted or "replace(/<[^>]*>/g, \"\")" in untrusted
