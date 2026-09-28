from __future__ import annotations

import re
from typing import Any, ClassVar

import httpx

from app.adapters.providers.connectors.files import ingestible
from app.adapters.providers.connectors.oauth import OAuthConnectorMixin
from app.application.sync_diff import diff_connector_files
from app.core.errors import ConnectorAuthExpiredError, ConnectorError, ValidationFailedError
from app.domain.ports.connector import DataSourceConnector
from app.domain.registry import register
from app.domain.types import (
    ConnectorCapabilities,
    ConnectorDefinition,
    ConnectorFile,
    ConnectorLocation,
    DocumentChange,
)

_DRIVE = "https://www.googleapis.com/drive/v3"
_TIMEOUT = httpx.Timeout(60.0)
_EXPORT = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}
MY_DRIVE = "__my_drive__"
SHARED_WITH_ME = "__shared_with_me__"
SHARED_DRIVES = "__shared_drives__"
_FOLDER_URL = re.compile(r"/folders/([a-zA-Z0-9_-]{10,})", re.I)
_FILE_URL = re.compile(r"/file/d/([a-zA-Z0-9_-]{10,})", re.I)
_DOCS_URL = re.compile(
    r"docs\.google\.com/(?:document|spreadsheets|presentation)/d/([a-zA-Z0-9_-]{10,})",
    re.I,
)
_OPEN_ID = re.compile(r"[?&]id=([a-zA-Z0-9_-]{10,})", re.I)
_BARE_ID = re.compile(r"^[a-zA-Z0-9_-]{10,}$")


def parse_drive_resource(raw: str) -> str:
    """Extract a Drive file/folder id from a sharing URL or a pasted id."""
    text = (raw or "").strip()
    if not text:
        raise ValidationFailedError("Paste a Google Drive folder URL or folder ID")
    for pattern in (_FOLDER_URL, _FILE_URL, _DOCS_URL, _OPEN_ID):
        match = pattern.search(text)
        if match:
            return match.group(1)
    if _BARE_ID.match(text) and "://" not in text:
        return text
    raise ValidationFailedError(
        "That is not a Google Drive folder URL. Open the shared folder in Drive and copy the link "
        "(it contains /folders/...)."
    )


def _parent_query(parent: str) -> str:
    if parent == SHARED_WITH_ME:
        return "sharedWithMe = true and trashed = false"
    if parent in {"root", MY_DRIVE}:
        return "'root' in parents and trashed = false"
    escaped = parent.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}' in parents and trashed = false"


def _google_error_message(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
        if isinstance(err, dict):
            return str(err.get("message") or "")
        return str(err)
    except Exception:
        return (resp.text or "")[:200]


@register("connector", "google_drive")
class GoogleDriveConnector(OAuthConnectorMixin, DataSourceConnector):
    oauth_id = "google_drive"
    definition: ClassVar[ConnectorDefinition] = ConnectorDefinition(
        id="google_drive",
        name="Google Drive",
        description="Sign in with Google, then pick My Drive, Shared with me, a shared drive, or paste a team folder URL.",
        icon="drive",
        authentication="oauth2",
        mock=False,
        capabilities=ConnectorCapabilities(browse=True, subscribe=True, incremental_sync=True),
    )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}"}

    async def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, headers=self._headers(), params=params)
        if resp.status_code in {401, 403}:
            message = _google_error_message(resp)
            if resp.status_code == 403 and message and "auth" not in message.lower():
                raise ConnectorError(
                    "This Google account cannot open that folder. Sign in with the account that has access, "
                    "then paste the shared folder URL."
                )
            raise ConnectorAuthExpiredError("Google Drive authorization expired")
        if resp.status_code == 404:
            raise ValidationFailedError(
                "Google Drive could not find that folder. Check the URL and that this account can open it."
            )
        if resp.status_code >= 400:
            detail = _google_error_message(resp) or f"status {resp.status_code}"
            raise ConnectorError(f"Google Drive request failed ({detail})")
        return resp

    async def resolve_location(self, raw: str) -> ConnectorLocation:
        resource_id = parse_drive_resource(raw)
        row = (
            await self._get(
                f"{_DRIVE}/files/{resource_id}",
                params={
                    "fields": "id,name,mimeType,parents,driveId,shortcutDetails",
                    "supportsAllDrives": "true",
                },
            )
        ).json()
        mime = row.get("mimeType") or ""
        if mime == "application/vnd.google-apps.shortcut":
            target = (row.get("shortcutDetails") or {}).get("targetId")
            if not target:
                raise ValidationFailedError("That Drive shortcut does not point at a folder")
            return await self.resolve_location(target)
        if mime == "application/vnd.google-apps.folder":
            return ConnectorLocation(
                id=row["id"],
                name=row.get("name") or "Folder",
                path=row.get("name") or "",
                parent_id=(row.get("parents") or [None])[0],
            )
        parents = row.get("parents") or []
        if parents:
            return await self.resolve_location(parents[0])
        raise ValidationFailedError("That link is a file, not a folder")

    async def list_locations(self, parent_id: str | None = None) -> list[ConnectorLocation]:
        items = await self.browse(parent_id or "root")
        return [i for i in items if isinstance(i, ConnectorLocation)]

    async def browse(self, location_id: str) -> list[ConnectorLocation | ConnectorFile]:
        parent = location_id or "root"
        if parent in {"root", MY_DRIVE}:
            special = [
                ConnectorLocation(
                    id=SHARED_WITH_ME,
                    name="Shared with me",
                    path="Shared with me",
                    parent_id="root",
                ),
                ConnectorLocation(
                    id=SHARED_DRIVES,
                    name="Shared drives",
                    path="Shared drives",
                    parent_id="root",
                ),
            ]
            return special + await self._browse_children("root" if parent == "root" else "root")
        return await self._browse_children(parent)

    async def _browse_children(self, parent: str) -> list[ConnectorLocation | ConnectorFile]:
        files: list[dict] = []
        if parent == SHARED_DRIVES:
            files = await self._list_shared_drives()
        else:
            page_token: str | None = None
            while True:
                params: dict[str, str] = {
                    "q": _parent_query(parent),
                    "fields": "nextPageToken,files(id,name,mimeType,md5Checksum,modifiedTime,size,parents)",
                    "pageSize": "200",
                    "supportsAllDrives": "true",
                    "includeItemsFromAllDrives": "true",
                }
                if page_token:
                    params["pageToken"] = page_token
                data = (await self._get(f"{_DRIVE}/files", params=params)).json()
                files.extend(data.get("files") or [])
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
        out: list[ConnectorLocation | ConnectorFile] = []
        for row in files:
            if row.get("mimeType") == "application/vnd.google-apps.folder":
                out.append(
                    ConnectorLocation(
                        id=row["id"],
                        name=row.get("name") or "Folder",
                        path=row.get("name") or "",
                        parent_id=parent,
                    )
                )
            else:
                file = self._to_file(row, parent)
                if file:
                    out.append(file)
        return out

    async def _list_shared_drives(self) -> list[dict]:
        drives: list[dict] = []
        page_token: str | None = None
        while True:
            params: dict[str, str] = {"pageSize": "100"}
            if page_token:
                params["pageToken"] = page_token
            data = (await self._get(f"{_DRIVE}/drives", params=params)).json()
            for row in data.get("drives") or []:
                drives.append(
                    {
                        "id": row["id"],
                        "name": row.get("name") or "Shared drive",
                        "mimeType": "application/vnd.google-apps.folder",
                    }
                )
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return drives

    def _to_file(self, row: dict, parent: str) -> ConnectorFile | None:
        mime = row.get("mimeType") or "application/octet-stream"
        name = row.get("name") or "file"
        if mime not in _EXPORT and not ingestible(name, mime):
            return None
        revision = row.get("md5Checksum") or row.get("modifiedTime") or "1"
        return ConnectorFile(
            source_file_id=row["id"],
            path=name,
            name=name,
            parent_id=parent,
            revision=revision,
            checksum=revision,
            mime_type="text/plain" if mime in _EXPORT else mime,
            size_bytes=int(row["size"]) if row.get("size") else None,
            modified_at=row.get("modifiedTime"),
        )

    async def list_files(self) -> list[ConnectorFile]:
        location_id = (self.config or {}).get("location_id") or "root"
        include = bool((self.config or {}).get("include_subfolders", True))
        files: list[ConnectorFile] = []
        queue = [location_id]
        seen: set[str] = set()
        while queue:
            parent = queue.pop()
            if parent in seen:
                continue
            seen.add(parent)
            for item in await self.browse(parent):
                if isinstance(item, ConnectorLocation):
                    if include:
                        queue.append(item.id)
                else:
                    files.append(item)
        return files

    async def get_file(self, source_file_id: str) -> bytes:
        meta = (
            await self._get(
                f"{_DRIVE}/files/{source_file_id}",
                params={"fields": "id,name,mimeType", "supportsAllDrives": "true"},
            )
        ).json()
        mime = meta.get("mimeType") or ""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            if mime in _EXPORT:
                resp = await client.get(
                    f"{_DRIVE}/files/{source_file_id}/export",
                    headers=self._headers(),
                    params={"mimeType": _EXPORT[mime]},
                )
            else:
                resp = await client.get(
                    f"{_DRIVE}/files/{source_file_id}",
                    headers=self._headers(),
                    params={"alt": "media", "supportsAllDrives": "true"},
                )
        if resp.status_code in {401, 403}:
            raise ConnectorAuthExpiredError("Google Drive authorization expired")
        if resp.status_code >= 400:
            raise ConnectorError(f"Google Drive download failed ({resp.status_code})")
        return resp.content

    async def get_metadata(self, source_file_id: str) -> ConnectorFile:
        row = (
            await self._get(
                f"{_DRIVE}/files/{source_file_id}",
                params={"fields": "id,name,mimeType,md5Checksum,modifiedTime,size,parents", "supportsAllDrives": "true"},
            )
        ).json()
        file = self._to_file(row, (row.get("parents") or ["root"])[0])
        if file is None:
            raise ConnectorError("File type is not ingestible")
        return file

    async def detect_changes(self, previous: list[ConnectorFile]) -> list[DocumentChange]:
        return diff_connector_files(previous, await self.list_files())

    async def health_check(self) -> dict[str, Any]:
        await self._get("https://www.googleapis.com/oauth2/v2/userinfo")
        return {"status": "healthy", "provider": "google_drive"}
