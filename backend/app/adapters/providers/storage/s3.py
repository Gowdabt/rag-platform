from __future__ import annotations

from datetime import timedelta
from functools import partial

import anyio

from app.config.models import StorageConfig
from app.config.secrets import is_secret_ref, resolve_secret
from app.core.context import RequestContext
from app.domain.ports.storage import ObjectStore
from app.domain.registry import register


@register("storage", "s3")
class S3ObjectStore(ObjectStore):
    def __init__(self, config: StorageConfig, ctx: RequestContext):
        super().__init__(config, ctx)

    def _client(self):
        import boto3

        kwargs: dict = {"region_name": self.config.region}
        if self.config.endpoint_url:
            url = (
                resolve_secret(self.config.endpoint_url)
                if is_secret_ref(self.config.endpoint_url)
                else self.config.endpoint_url
            )
            kwargs["endpoint_url"] = url
        access = self.config.access_key
        secret = self.config.secret_key
        if access and is_secret_ref(access):
            access = resolve_secret(access)
        if secret and is_secret_ref(secret):
            secret = resolve_secret(secret)
        if access and secret:
            kwargs["aws_access_key_id"] = access
            kwargs["aws_secret_access_key"] = secret
        return boto3.client("s3", **kwargs)

    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        extra = {}
        if content_type:
            extra["ContentType"] = content_type
        await anyio.to_thread.run_sync(
            partial(self._client().put_object, Bucket=self.config.bucket, Key=key, Body=data, **extra)
        )
        return key

    async def get(self, key: str) -> bytes:
        def _get():
            obj = self._client().get_object(Bucket=self.config.bucket, Key=key)
            return obj["Body"].read()

        return await anyio.to_thread.run_sync(_get)

    async def delete(self, key: str) -> None:
        await anyio.to_thread.run_sync(
            partial(self._client().delete_object, Bucket=self.config.bucket, Key=key)
        )

    async def signed_url(self, key: str, *, expires: timedelta = timedelta(minutes=15)) -> str:
        def _url():
            return self._client().generate_presigned_url(
                "get_object",
                Params={"Bucket": self.config.bucket, "Key": key},
                ExpiresIn=int(expires.total_seconds()),
            )

        return await anyio.to_thread.run_sync(_url)
