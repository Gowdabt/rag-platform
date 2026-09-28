from __future__ import annotations

from typing import Any, ClassVar

import httpx

from app.adapters.providers.connectors.files import ingestible
from app.adapters.providers.connectors.oauth import OAuthConnectorMixin
from app.application.sync_diff import diff_connector_files
from app.core.errors import ConnectorAuthExpiredError, ConnectorError
from app.domain.ports.connector import DataSourceConnector
from app.domain.registry import register
from app.domain.types import ConnectorCapabilities, ConnectorDefinition, ConnectorFile, ConnectorLocation, DocumentChange

_GRAPH = "https://graph.microsoft.com/v1.0"
_TIMEOUT = httpx.Timeout(60.0)


class MicrosoftGraphConnector(OAuthConnectorMixin, DataSourceConnector):
    """OneDrive and SharePoint document libraries through Microsoft Graph."""

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}"}

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.request(method, url, headers=self._headers(), **kwargs)
        if resp.status_code in {401, 403}:
            raise ConnectorAuthExpiredError("Microsoft authorization expired")
        if resp.status_code >= 400:
            raise ConnectorError(f"Microsoft Graph request failed ({resp.status_code})")
        return resp

    async def _pages(self, url: str) -> list[dict]:
        items: list[dict] = []
        next_url: str | None = url
        while next_url:
            data = (await self._request("GET", next_url)).json()
            items.extend(data.get("value") or [])
            next_url = data.get("@odata.nextLink")
        return items

    def _parse_location(self, location_id: str | None) -> tuple[str, str]:
        raw = location_id or "root"
        if raw == "root":
            return "", "root"
        if raw.startswith("site:"):
            return raw, "site"
        if ":" in raw:
            drive_id, item_id = raw.split(":", 1)
            return drive_id, item_id or "root"
        return "", raw

    def _loc_id(self, drive_id: str, item_id: str) -> str:
        return f"{drive_id}:{item_id}" if drive_id else item_id

    async def list_locations(self, parent_id: str | None = None) -> list[ConnectorLocation]:
        return [i for i in await self.browse(parent_id or "root") if isinstance(i, ConnectorLocation)]

    async def _sharepoint_root(self) -> list[ConnectorLocation | ConnectorFile]:
        sites: list[dict] = []
        try:
            sites = await self._pages(f"{_GRAPH}/me/followedSites")
        except ConnectorError:
            sites = []
        if not sites:
            try:
                sites = await self._pages(f"{_GRAPH}/sites?search=*&$top=50")
            except ConnectorError:
                sites = []
        items: list[ConnectorLocation | ConnectorFile] = []
        for site in sites:
            sid = site.get("id")
            if not sid:
                continue
            items.append(
                ConnectorLocation(
                    id=f"site:{sid}",
                    name=site.get("displayName") or site.get("name") or "Site",
                    type="site",
                    path=site.get("webUrl") or site.get("name") or "",
                )
            )
        if items:
            return items
        return await self._onedrive_root()

    async def _onedrive_root(self) -> list[ConnectorLocation | ConnectorFile]:
        drives = await self._pages(f"{_GRAPH}/me/drives")
        return [
            ConnectorLocation(
                id=f"{drive['id']}:root",
                name=drive.get("name") or "Drive",
                type="drive",
                path=drive.get("name") or "",
            )
            for drive in drives
            if drive.get("id")
        ]

    async def browse(self, location_id: str) -> list[ConnectorLocation | ConnectorFile]:
        if not location_id or location_id == "root":
            if getattr(self, "oauth_id", "") == "sharepoint":
                return await self._sharepoint_root()
            return await self._onedrive_root()
        if location_id.startswith("site:"):
            site_id = location_id[5:]
            drives = await self._pages(f"{_GRAPH}/sites/{site_id}/drives")
            return [
                ConnectorLocation(
                    id=f"{drive['id']}:root",
                    name=drive.get("name") or "Library",
                    type="drive",
                    path=drive.get("name") or "",
                    parent_id=location_id,
                )
                for drive in drives
                if drive.get("id")
            ]
        drive_id, item_id = self._parse_location(location_id)
        if item_id == "root":
            url = f"{_GRAPH}/drives/{drive_id}/root/children"
        else:
            url = f"{_GRAPH}/drives/{drive_id}/items/{item_id}/children"
        rows = await self._pages(url)
        out: list[ConnectorLocation | ConnectorFile] = []
        for row in rows:
            if "folder" in row:
                out.append(
                    ConnectorLocation(
                        id=self._loc_id(drive_id, row["id"]),
                        name=row.get("name") or "Folder",
                        path=row.get("name") or "",
                        parent_id=location_id,
                    )
                )
            else:
                file = self._to_file(row, drive_id)
                if file:
                    out.append(file)
        return out

    def _to_file(self, row: dict, drive_id: str) -> ConnectorFile | None:
        name = row.get("name") or "file"
        mime = (row.get("file") or {}).get("mimeType")
        if not ingestible(name, mime):
            return None
        etag = row.get("eTag") or row.get("cTag") or row.get("lastModifiedDateTime") or "1"
        return ConnectorFile(
            source_file_id=self._loc_id(drive_id, row["id"]),
            path=row.get("parentReference", {}).get("path") or name,
            name=name,
            parent_id=self._loc_id(drive_id, (row.get("parentReference") or {}).get("id") or "root"),
            revision=etag,
            etag=etag,
            checksum=etag,
            mime_type=mime,
            size_bytes=int(row["size"]) if row.get("size") else None,
            modified_at=row.get("lastModifiedDateTime"),
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
        drive_id, item_id = self._parse_location(source_file_id)
        url = f"{_GRAPH}/drives/{drive_id}/items/{item_id}/content"
        resp = await self._request("GET", url, follow_redirects=True)
        return resp.content

    async def get_metadata(self, source_file_id: str) -> ConnectorFile:
        drive_id, item_id = self._parse_location(source_file_id)
        row = (await self._request("GET", f"{_GRAPH}/drives/{drive_id}/items/{item_id}")).json()
        file = self._to_file(row, drive_id)
        if file is None:
            raise ConnectorError("File type is not ingestible")
        return file

    async def detect_changes(self, previous: list[ConnectorFile]) -> list[DocumentChange]:
        return diff_connector_files(previous, await self.list_files())

    async def health_check(self) -> dict[str, Any]:
        await self._request("GET", f"{_GRAPH}/me")
        return {"status": "healthy", "provider": self.definition.id}


@register("connector", "onedrive")
class OneDriveConnector(MicrosoftGraphConnector):
    oauth_id = "onedrive"
    definition: ClassVar[ConnectorDefinition] = ConnectorDefinition(
        id="onedrive",
        name="OneDrive",
        description="Sign in with Microsoft at runtime and sync OneDrive folders. Session tokens are stored encrypted.",
        icon="onedrive",
        authentication="oauth2",
        mock=False,
        capabilities=ConnectorCapabilities(browse=True, subscribe=True, incremental_sync=True),
    )


@register("connector", "sharepoint")
class SharePointConnector(MicrosoftGraphConnector):
    oauth_id = "sharepoint"
    definition: ClassVar[ConnectorDefinition] = ConnectorDefinition(
        id="sharepoint",
        name="SharePoint",
        description="Sign in with Microsoft at runtime and sync SharePoint libraries. Uses the same client as OneDrive.",
        icon="sharepoint",
        authentication="oauth2",
        mock=False,
        capabilities=ConnectorCapabilities(browse=True, subscribe=True, incremental_sync=True),
    )
