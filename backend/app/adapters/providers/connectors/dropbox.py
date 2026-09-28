from __future__ import annotations

import json
from typing import Any, ClassVar

import httpx

from app.adapters.providers.connectors.files import ingestible, mime_for
from app.adapters.providers.connectors.oauth import OAuthConnectorMixin
from app.application.sync_diff import diff_connector_files
from app.core.errors import ConnectorAuthExpiredError, ConnectorError
from app.domain.ports.connector import DataSourceConnector
from app.domain.registry import register
from app.domain.types import ConnectorCapabilities, ConnectorDefinition, ConnectorFile, ConnectorLocation, DocumentChange

_API = "https://api.dropboxapi.com/2"
_CONTENT = "https://content.dropboxapi.com/2"
_TIMEOUT = httpx.Timeout(60.0)


@register("connector", "dropbox")
class DropboxConnector(OAuthConnectorMixin, DataSourceConnector):
    oauth_id = "dropbox"
    definition: ClassVar[ConnectorDefinition] = ConnectorDefinition(
        id="dropbox",
        name="Dropbox",
        description="Sign in to Dropbox at runtime and sync a folder. Session tokens are stored encrypted.",
        icon="dropbox",
        authentication="oauth2",
        mock=False,
        capabilities=ConnectorCapabilities(browse=True, subscribe=True, incremental_sync=True),
    )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}

    def _path(self, location_id: str | None) -> str:
        if not location_id or location_id in {"root", "/"}:
            return ""
        return location_id if location_id.startswith("/") else f"/{location_id}"

    async def _rpc(self, path: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(f"{_API}{path}", headers=self._headers(), json=payload)
        if resp.status_code in {401, 403}:
            raise ConnectorAuthExpiredError("Dropbox authorization expired")
        if resp.status_code >= 400:
            raise ConnectorError(f"Dropbox request failed ({resp.status_code})")
        return resp.json()

    async def list_locations(self, parent_id: str | None = None) -> list[ConnectorLocation]:
        return [i for i in await self.browse(parent_id or "root") if isinstance(i, ConnectorLocation)]

    async def browse(self, location_id: str) -> list[ConnectorLocation | ConnectorFile]:
        path = self._path(location_id)
        entries: list[dict] = []
        data = await self._rpc("/files/list_folder", {"path": path, "recursive": False})
        entries.extend(data.get("entries") or [])
        while data.get("has_more"):
            data = await self._rpc("/files/list_folder/continue", {"cursor": data["cursor"]})
            entries.extend(data.get("entries") or [])
        return self._entries(entries)

    def _entries(self, entries: list[dict]) -> list[ConnectorLocation | ConnectorFile]:
        items: list[ConnectorLocation | ConnectorFile] = []
        for row in entries:
            tag = row.get(".tag")
            path = row.get("path_display") or row.get("path_lower") or ""
            name = row.get("name") or path.rsplit("/", 1)[-1]
            if tag == "folder":
                items.append(ConnectorLocation(id=path, name=name, path=path, parent_id=path.rsplit("/", 1)[0] or "root"))
            elif tag == "file" and ingestible(name):
                rev = row.get("rev") or row.get("content_hash") or "1"
                items.append(
                    ConnectorFile(
                        source_file_id=row.get("id") or path,
                        path=path,
                        name=name,
                        parent_id=path.rsplit("/", 1)[0] or "root",
                        revision=rev,
                        checksum=row.get("content_hash") or rev,
                        mime_type=mime_for(name),
                        size_bytes=int(row["size"]) if row.get("size") else None,
                        modified_at=row.get("server_modified"),
                    )
                )
        return items

    async def list_files(self) -> list[ConnectorFile]:
        location_id = (self.config or {}).get("location_id") or ""
        include = bool((self.config or {}).get("include_subfolders", True))
        data = await self._rpc("/files/list_folder", {"path": self._path(location_id), "recursive": include})
        entries = list(data.get("entries") or [])
        while data.get("has_more"):
            data = await self._rpc("/files/list_folder/continue", {"cursor": data["cursor"]})
            entries.extend(data.get("entries") or [])
        return [item for item in self._entries(entries) if isinstance(item, ConnectorFile)]

    async def get_file(self, source_file_id: str) -> bytes:
        arg = {"path": source_file_id if source_file_id.startswith("/") else source_file_id}
        # Dropbox download prefers path; id: prefix works for ids
        if not source_file_id.startswith("/") and not source_file_id.startswith("id:"):
            arg = {"path": f"id:{source_file_id}"}
        headers = {"Authorization": f"Bearer {self._token()}", "Dropbox-API-Arg": json.dumps(arg)}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(f"{_CONTENT}/files/download", headers=headers)
        if resp.status_code in {401, 403}:
            raise ConnectorAuthExpiredError("Dropbox authorization expired")
        if resp.status_code >= 400:
            raise ConnectorError(f"Dropbox download failed ({resp.status_code})")
        return resp.content

    async def get_metadata(self, source_file_id: str) -> ConnectorFile:
        path = source_file_id if source_file_id.startswith("/") else f"id:{source_file_id}"
        row = await self._rpc("/files/get_metadata", {"path": path})
        items = self._entries([row])
        if not items or not isinstance(items[0], ConnectorFile):
            raise ConnectorError("Dropbox file not ingestible")
        return items[0]

    async def detect_changes(self, previous: list[ConnectorFile]) -> list[DocumentChange]:
        return diff_connector_files(previous, await self.list_files())

    async def health_check(self) -> dict[str, Any]:
        await self._rpc("/users/get_current_account", {})
        return {"status": "healthy", "provider": "dropbox"}
