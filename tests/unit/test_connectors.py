from uuid import uuid4

from app.application.providers import load_providers
from app.application.sync_diff import diff_connector_files
from app.core.context import RequestContext
from app.core.crypto import LocalTokenCipher
from app.core.errors import ConnectorAuthExpiredError
from app.domain.registry import registry
from app.domain.types import ConnectorFile
from app.main import create_app
from fastapi.testclient import TestClient


def test_mock_connectors_register_when_enabled(monkeypatch):
    monkeypatch.setenv("RAG_CONNECTOR_MOCKS", "1")
    load_providers()
    for name in ("mock_google_drive", "mock_onedrive", "mock_dropbox", "mock_s3", "mock_local_fs"):
        assert registry.contains("connector", name)


def test_health_is_authenticated_surface_without_provider_inventory():
    with TestClient(create_app()) as client:
        body = client.get("/api/v1/health").json()
    assert body["status"] in {"ok", "degraded"}
    assert "registered_providers" not in body


def test_catalog_requires_auth():
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/connectors/catalog").status_code == 401


def test_token_cipher_roundtrip():
    cipher = LocalTokenCipher("unit-test-secret")
    token = cipher.encrypt("access-token-value")
    assert "access-token-value" not in token
    assert cipher.decrypt(token) == "access-token-value"


def test_token_cipher_rejects_tampering():
    cipher = LocalTokenCipher("unit-test-secret")
    token = cipher.encrypt("secret")
    try:
        cipher.decrypt(token[:-2] + "ab")
        assert False, "expected invalid token"
    except ValueError:
        pass


def test_diff_uses_file_id_not_filename():
    previous = [ConnectorFile(source_file_id="abc", path="/old/name.md", checksum="1")]
    current = [ConnectorFile(source_file_id="abc", path="/new/renamed.md", checksum="1")]
    changes = diff_connector_files(previous, current)
    assert len(changes) == 1
    assert changes[0].event_type == "DOCUMENT_MOVED"
    assert changes[0].file.source_file_id == "abc"


def test_diff_detects_update_and_delete():
    previous = [
        ConnectorFile(source_file_id="keep", path="/a.md", checksum="1"),
        ConnectorFile(source_file_id="gone", path="/b.md", checksum="1"),
    ]
    current = [ConnectorFile(source_file_id="keep", path="/a.md", checksum="2")]
    events = {c.event_type for c in diff_connector_files(previous, current)}
    assert events == {"DOCUMENT_UPDATED", "DOCUMENT_DELETED"}


async def _drive():
    from app.adapters.providers.connectors.mock import MockGoogleDriveConnector

    return MockGoogleDriveConnector({}, RequestContext(request_id="t", tenant_id=uuid4()))


def test_mock_drive_browse_and_stable_ids():
    import asyncio

    async def run():
        connector = await _drive()
        folders = await connector.list_locations("root")
        names = {f.name for f in folders}
        assert "Engineering" in names
        files = await connector.list_files()
        ids = {f.source_file_id for f in files}
        assert "file_arch" in ids
        body = (await connector.get_file("file_arch")).decode()
        assert "Asset Hierarchy" in body
        previous = [ConnectorFile(source_file_id="file_arch", path="/Engineering/old.md", checksum="x")]
        changes = await connector.detect_changes(previous)
        kinds = {c.event_type for c in changes}
        assert "DOCUMENT_CREATED" in kinds or "DOCUMENT_UPDATED" in kinds or "DOCUMENT_MOVED" in kinds

    asyncio.run(run())


def test_mock_auth_expired():
    import asyncio

    from app.adapters.providers.connectors.mock import MockGoogleDriveConnector

    async def run():
        connector = MockGoogleDriveConnector({"simulate": "auth_expired"}, RequestContext(request_id="t"))
        try:
            await connector.list_files()
            assert False
        except ConnectorAuthExpiredError:
            pass

    asyncio.run(run())
