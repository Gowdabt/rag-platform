from pathlib import Path
from uuid import uuid4

import pytest
from app.adapters.providers.connectors.local_fs import LocalFolderConnector, resolve_allowed_path
from app.adapters.providers.connectors.oauth import build_authorization_url, oauth_is_configured
from app.application.connectors import next_sync_at
from app.application.providers import load_providers
from app.core.context import RequestContext
from app.core.errors import ValidationFailedError
from app.domain.registry import registry
from app.main import create_app
from fastapi.testclient import TestClient


def test_real_connectors_are_registered():
    load_providers()
    for name in ("local_fs", "s3", "google_drive", "onedrive", "sharepoint", "dropbox"):
        assert registry.contains("connector", name)


def test_health_lists_realtime_connectors():
    with TestClient(create_app()) as client:
        body = client.get("/api/v1/health").json()
    assert body["providers"]["llm"] == "ollama"
    assert "registered_providers" not in body
    assert "models" not in (body.get("ollama") or {})


def test_catalog_hides_mocks_by_default(monkeypatch):
    monkeypatch.delenv("RAG_CONNECTOR_MOCKS", raising=False)
    load_providers()
    from app.application.connectors import list_connector_catalog

    ids = {row["id"] for row in list_connector_catalog()}
    assert "local_fs" in ids
    assert "google_drive" in ids
    assert "mock_google_drive" not in ids


def test_catalog_can_include_mocks(monkeypatch):
    monkeypatch.setenv("RAG_CONNECTOR_MOCKS", "1")
    load_providers()
    from app.application.connectors import list_connector_catalog

    ids = {row["id"] for row in list_connector_catalog()}
    assert "mock_google_drive" in ids


def test_oauth_authorization_url_uses_real_google_endpoint(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    assert oauth_is_configured("google_drive") is True
    url = build_authorization_url("google_drive", redirect_uri="http://127.0.0.1:5173/sources", state="abc")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client-id" in url
    assert "abc" in url


def test_oauth_accepts_saved_clients_without_env(monkeypatch):
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("MICROSOFT_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("MICROSOFT_OAUTH_CLIENT_SECRET", raising=False)
    clients = {
        "google": {"client_id": "from-ui", "client_secret": "ui-secret"},
        "microsoft": {"client_id": "ms-id", "client_secret": "ms-secret"},
    }
    assert oauth_is_configured("google_drive", clients) is True
    assert oauth_is_configured("onedrive", clients) is True
    assert oauth_is_configured("sharepoint", clients) is True
    url = build_authorization_url(
        "google_drive",
        redirect_uri="http://127.0.0.1:5173/sources",
        state="abc",
        clients=clients,
    )
    assert "from-ui" in url
    ms = build_authorization_url(
        "onedrive",
        redirect_uri="http://127.0.0.1:5173/sources",
        state="xyz",
        clients=clients,
    )
    assert ms.startswith("https://login.microsoftonline.com/")
    scope = ms.split("scope=")[1].split("&")[0]
    assert "+" not in scope
    assert "%20" in scope


def test_catalog_marks_oauth_configured_from_clients(monkeypatch):
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("RAG_CONNECTOR_MOCKS", raising=False)
    load_providers()
    from app.application.connectors import list_connector_catalog

    unconfigured = next(row for row in list_connector_catalog() if row["id"] == "google_drive")
    assert unconfigured["configured"] is False
    configured = next(
        row
        for row in list_connector_catalog({"google": {"client_id": "id", "client_secret": "secret"}})
        if row["id"] == "google_drive"
    )
    assert configured["configured"] is True
    assert configured["oauth_group"] == "google"


def test_oauth_runtime_overlay_wins_over_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "env-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "env-secret")
    from app.adapters.providers.connectors.oauth import encrypt_secret

    clients = {"google": {"client_id": "runtime-id", "client_secret": encrypt_secret("runtime-secret")}}
    url = build_authorization_url(
        "google_drive",
        redirect_uri="http://127.0.0.1:5173/sources",
        state="st",
        clients=clients,
    )
    assert "runtime-id" in url
    assert "env-id" not in url


def test_oauth_redirect_uri_must_be_local():
    from app.adapters.providers.connectors.oauth import assert_oauth_redirect_uri

    assert assert_oauth_redirect_uri("http://127.0.0.1:5173/sources").endswith("/sources")
    with pytest.raises(ValidationFailedError):
        assert_oauth_redirect_uri("https://evil.example/callback")


def test_oauth_requires_client_at_runtime_or_env(monkeypatch):
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    with pytest.raises(ValidationFailedError):
        build_authorization_url("google_drive", redirect_uri="http://127.0.0.1:5173/sources", state="x")


@pytest.mark.asyncio
async def test_local_fs_reads_real_files_and_keeps_inode_identity(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CONNECTOR_FS_ROOTS", str(tmp_path))
    folder = tmp_path / "kb"
    folder.mkdir()
    doc = folder / "policy.md"
    doc.write_text("Employees receive twelve wellness days.\n", encoding="utf-8")
    ctx = RequestContext(request_id="t", tenant_id=uuid4())
    connector = LocalFolderConnector({"root_path": str(tmp_path)}, ctx)
    await connector.connect()
    children = await connector.browse(str(folder))
    names = {item.name for item in children}
    assert "policy.md" in names
    files = await connector.list_files()
    policy = next(f for f in files if f.name == "policy.md")
    original_id = policy.source_file_id
    renamed = folder / "leave-policy.md"
    doc.rename(renamed)
    files_after = await connector.list_files()
    moved = next(f for f in files_after if f.name == "leave-policy.md")
    assert moved.source_file_id == original_id
    body = (await connector.get_file(original_id)).decode()
    assert "twelve wellness days" in body


def test_local_fs_rejects_path_outside_allowlist(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CONNECTOR_FS_ROOTS", str(tmp_path))
    with pytest.raises(ValidationFailedError):
        resolve_allowed_path("/etc")


def test_local_fs_default_roots_include_project_data_sources(monkeypatch):
    monkeypatch.delenv("CONNECTOR_FS_ROOTS", raising=False)
    from app.adapters.providers.connectors.local_fs import filesystem_roots, list_host_folders

    project_sources = (Path(__file__).resolve().parents[2] / "data" / "sources").resolve()
    roots = filesystem_roots()
    assert project_sources in roots
    assert (Path.home() / "Documents").resolve() not in roots
    assert (Path.home() / "Desktop").resolve() not in roots
    assert resolve_allowed_path(project_sources) == project_sources
    with pytest.raises(ValidationFailedError):
        resolve_allowed_path("/etc")
    listing = list_host_folders(None)
    assert listing["at_roots"] is True
    assert any(item["path"] == str(project_sources) for item in listing["items"])
    nested = list_host_folders(str(project_sources))
    assert nested["at_roots"] is False
    assert nested["path"] == str(project_sources)

    tenant_id = "11111111-1111-1111-1111-111111111111"
    user_id = "22222222-2222-2222-2222-222222222222"
    user_roots = filesystem_roots(isolation="user", tenant_id=tenant_id, user_id=user_id)
    expected = (project_sources / tenant_id / user_id).resolve()
    assert expected in user_roots
    assert expected.exists()



def test_next_sync_at_for_hourly():
    assert next_sync_at("manual") is None
    assert next_sync_at("hourly") is not None


def test_parse_google_drive_folder_url():
    from app.adapters.providers.connectors.google_drive import parse_drive_resource

    folder_id = "1aBcD_efGhi-jkLmnopQRST"
    assert parse_drive_resource(f"https://drive.google.com/drive/folders/{folder_id}?usp=sharing") == folder_id
    assert parse_drive_resource(f"https://drive.google.com/drive/u/0/folders/{folder_id}") == folder_id
    assert parse_drive_resource(f"https://drive.google.com/open?id={folder_id}") == folder_id
    assert parse_drive_resource(folder_id) == folder_id
    with pytest.raises(ValidationFailedError):
        parse_drive_resource("https://example.com/not-drive")
