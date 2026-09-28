from __future__ import annotations

import os
from typing import Any, ClassVar

from app.adapters.providers.connectors.files import ingestible, mime_for
from app.application.sync_diff import diff_connector_files
from app.config.secrets import is_secret_ref, resolve_secret
from app.core.errors import ConnectorError, ValidationFailedError
from app.domain.ports.connector import DataSourceConnector
from app.domain.registry import register
from app.domain.types import (
    ConnectorCapabilities,
    ConnectorDefinition,
    ConnectorFile,
    ConnectorLocation,
    DocumentChange,
)


@register("connector", "s3")
class S3Connector(DataSourceConnector):
    """Lists and downloads objects from a real S3/MinIO bucket via boto3."""

    definition: ClassVar[ConnectorDefinition] = ConnectorDefinition(
        id="s3",
        name="Amazon S3",
        description="Sync objects from an S3 or MinIO bucket. Uses connector settings, or S3_* environment variables.",
        icon="s3",
        authentication="api_key",
        mock=False,
        capabilities=ConnectorCapabilities(browse=True, subscribe=True, incremental_sync=True),
    )

    def _client(self):
        import boto3

        cfg = self.config or {}
        kwargs: dict[str, Any] = {"region_name": cfg.get("region") or os.environ.get("S3_REGION") or "us-east-1"}
        endpoint = cfg.get("endpoint_url") or os.environ.get("S3_ENDPOINT_URL")
        if endpoint:
            if is_secret_ref(endpoint):
                endpoint = resolve_secret(endpoint)
            kwargs["endpoint_url"] = endpoint
        access = cfg.get("access_key") or os.environ.get("S3_ACCESS_KEY")
        secret = cfg.get("secret_key") or os.environ.get("S3_SECRET_KEY")
        if access and is_secret_ref(access):
            access = resolve_secret(access)
        if secret and is_secret_ref(secret):
            secret = resolve_secret(secret)
        if access and secret:
            kwargs["aws_access_key_id"] = access
            kwargs["aws_secret_access_key"] = secret
        return boto3.client("s3", **kwargs)

    def _bucket(self) -> str:
        bucket = (self.config or {}).get("bucket") or os.environ.get("S3_BUCKET")
        if not bucket:
            raise ValidationFailedError("S3 bucket is required")
        return bucket

    def _prefix(self, location_id: str | None = None) -> str:
        if location_id and location_id not in {"root", ""}:
            return location_id.lstrip("/")
        return str((self.config or {}).get("prefix") or "").lstrip("/")

    async def connect(self) -> None:
        import anyio

        def _head():
            self._client().head_bucket(Bucket=self._bucket())

        try:
            await anyio.to_thread.run_sync(_head)
        except Exception as exc:
            raise ConnectorError("Unable to access S3 bucket") from exc

    async def disconnect(self) -> None:
        return None

    async def list_locations(self, parent_id: str | None = None) -> list[ConnectorLocation]:
        return [item for item in await self.browse(parent_id or "root") if isinstance(item, ConnectorLocation)]

    async def browse(self, location_id: str) -> list[ConnectorLocation | ConnectorFile]:
        import anyio

        prefix = self._prefix(location_id)
        if prefix and not prefix.endswith("/"):
            prefix = prefix + "/"

        def _list():
            return self._client().list_objects_v2(Bucket=self._bucket(), Prefix=prefix, Delimiter="/")

        try:
            data = await anyio.to_thread.run_sync(_list)
        except Exception as exc:
            raise ConnectorError("S3 list failed") from exc
        items: list[ConnectorLocation | ConnectorFile] = []
        for common in data.get("CommonPrefixes") or []:
            pfx = common.get("Prefix") or ""
            name = pfx.rstrip("/").rsplit("/", 1)[-1]
            items.append(ConnectorLocation(id=pfx.rstrip("/"), name=name, path=pfx, parent_id=location_id, type="folder"))
        for obj in data.get("Contents") or []:
            key = obj.get("Key") or ""
            if key.endswith("/"):
                continue
            name = key.rsplit("/", 1)[-1]
            if not ingestible(name):
                continue
            etag = str(obj.get("ETag") or "").strip('"')
            items.append(
                ConnectorFile(
                    source_file_id=key,
                    path=key,
                    name=name,
                    parent_id=prefix.rstrip("/") or "root",
                    revision=etag,
                    etag=etag,
                    checksum=etag,
                    mime_type=mime_for(name),
                    size_bytes=int(obj.get("Size") or 0),
                )
            )
        return items

    async def list_files(self) -> list[ConnectorFile]:
        import anyio

        prefix = self._prefix((self.config or {}).get("location_id"))
        include = bool((self.config or {}).get("include_subfolders", True))

        def _list():
            client = self._client()
            token = None
            keys = []
            while True:
                kwargs: dict[str, Any] = {"Bucket": self._bucket(), "Prefix": prefix}
                if not include:
                    kwargs["Delimiter"] = "/"
                if token:
                    kwargs["ContinuationToken"] = token
                page = client.list_objects_v2(**kwargs)
                keys.extend(page.get("Contents") or [])
                if not page.get("IsTruncated"):
                    break
                token = page.get("NextContinuationToken")
            return keys

        try:
            objects = await anyio.to_thread.run_sync(_list)
        except Exception as exc:
            raise ConnectorError("S3 list failed") from exc
        files: list[ConnectorFile] = []
        for obj in objects:
            key = obj.get("Key") or ""
            if key.endswith("/") or not ingestible(key):
                continue
            etag = str(obj.get("ETag") or "").strip('"')
            files.append(
                ConnectorFile(
                    source_file_id=key,
                    path=key,
                    name=key.rsplit("/", 1)[-1],
                    revision=etag,
                    etag=etag,
                    checksum=etag,
                    mime_type=mime_for(key),
                    size_bytes=int(obj.get("Size") or 0),
                )
            )
        return files

    async def get_file(self, source_file_id: str) -> bytes:
        import anyio

        def _get():
            obj = self._client().get_object(Bucket=self._bucket(), Key=source_file_id)
            return obj["Body"].read()

        try:
            return await anyio.to_thread.run_sync(_get)
        except Exception as exc:
            raise ConnectorError(f"S3 get failed for {source_file_id}") from exc

    async def get_metadata(self, source_file_id: str) -> ConnectorFile:
        import anyio

        def _head():
            return self._client().head_object(Bucket=self._bucket(), Key=source_file_id)

        try:
            data = await anyio.to_thread.run_sync(_head)
        except Exception as exc:
            raise ConnectorError(f"S3 head failed for {source_file_id}") from exc
        etag = str(data.get("ETag") or "").strip('"')
        return ConnectorFile(
            source_file_id=source_file_id,
            path=source_file_id,
            name=source_file_id.rsplit("/", 1)[-1],
            revision=etag,
            etag=etag,
            checksum=etag,
            mime_type=data.get("ContentType") or mime_for(source_file_id),
            size_bytes=int(data.get("ContentLength") or 0),
        )

    async def detect_changes(self, previous: list[ConnectorFile]) -> list[DocumentChange]:
        return diff_connector_files(previous, await self.list_files())

    async def health_check(self) -> dict[str, Any]:
        try:
            await self.connect()
            return {"status": "healthy", "provider": "s3", "bucket": self._bucket()}
        except Exception as exc:
            return {"status": "error", "provider": "s3", "error": str(exc)}
