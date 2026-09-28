from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.adapters.providers.connectors.google_drive import GoogleDriveConnector
from app.adapters.providers.connectors.s3 import S3Connector
from app.core.context import RequestContext


class _Resp:
    def __init__(self, payload=None, content=b"", status_code=200):
        self._payload = payload or {}
        self.content = content
        self.status_code = status_code

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_google_drive_lists_and_downloads_via_live_api_shape():
    ctx = RequestContext(request_id="t", tenant_id=uuid4())
    connector = GoogleDriveConnector({"access_token": "ya29.token"}, ctx)

    files_resp = _Resp(
        {
            "files": [
                {"id": "fld", "name": "Policies", "mimeType": "application/vnd.google-apps.folder"},
                {
                    "id": "file1",
                    "name": "pto.md",
                    "mimeType": "text/markdown",
                    "md5Checksum": "abc",
                    "size": "12",
                    "parents": ["root"],
                },
            ]
        }
    )
    media = _Resp(content=b"PTO is 18 days.")
    meta = _Resp({"id": "file1", "name": "pto.md", "mimeType": "text/markdown"})

    fake = MagicMock()
    fake.get = AsyncMock(side_effect=[files_resp, meta, media])
    fake.__aenter__ = AsyncMock(return_value=fake)
    fake.__aexit__ = AsyncMock(return_value=None)

    with patch("app.adapters.providers.connectors.google_drive.httpx.AsyncClient", return_value=fake):
        items = await connector.browse("root")
        names = {getattr(i, "name", None) for i in items}
        assert "Shared with me" in names
        assert "Shared drives" in names
        assert "Policies" in names
        assert "pto.md" in names
        body = await connector.get_file("file1")
        assert b"18 days" in body


@pytest.mark.asyncio
async def test_google_drive_resolves_shared_folder_url():
    ctx = RequestContext(request_id="t", tenant_id=uuid4())
    connector = GoogleDriveConnector({"access_token": "ya29.token"}, ctx)
    meta = _Resp(
        {
            "id": "1TeamFolder",
            "name": "Acme Shared KB",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": ["0ADrive"],
        }
    )
    fake = MagicMock()
    fake.get = AsyncMock(return_value=meta)
    fake.__aenter__ = AsyncMock(return_value=fake)
    fake.__aexit__ = AsyncMock(return_value=None)
    with patch("app.adapters.providers.connectors.google_drive.httpx.AsyncClient", return_value=fake):
        loc = await connector.resolve_location("https://drive.google.com/drive/folders/1TeamFolder?usp=sharing")
    assert loc.id == "1TeamFolder"
    assert loc.name == "Acme Shared KB"


@pytest.mark.asyncio
async def test_s3_lists_objects_from_bucket():
    ctx = RequestContext(request_id="t")
    connector = S3Connector({"bucket": "kb", "prefix": "docs"}, ctx)

    class Client:
        def list_objects_v2(self, **kwargs):
            return {
                "Contents": [
                    {"Key": "docs/runbook.md", "ETag": '"etag1"', "Size": 20},
                    {"Key": "docs/skip.bin", "ETag": '"x"', "Size": 2},
                ],
                "IsTruncated": False,
            }

        def get_object(self, **kwargs):
            class Body:
                def read(self):
                    return b"Restart the worker."

            return {"Body": Body()}

    with patch.object(S3Connector, "_client", return_value=Client()):
        files = await connector.list_files()
        assert [f.name for f in files] == ["runbook.md"]
        assert await connector.get_file("docs/runbook.md") == b"Restart the worker."
