from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from app.config.models import StorageConfig
from app.core.context import RequestContext
from app.core.errors import NotFoundError
from app.domain.ports.storage import ObjectStore
from app.domain.registry import register


@register("storage", "local_fs")
class LocalFilesystemStore(ObjectStore):
    def __init__(self, config: StorageConfig, ctx: RequestContext):
        super().__init__(config, ctx)
        self.root = Path(config.bucket).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root)):
            raise NotFoundError("Invalid storage key")
        return path

    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise NotFoundError("Object not found")
        return path.read_bytes()

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    async def signed_url(self, key: str, *, expires: timedelta = timedelta(minutes=15)) -> str:
        return f"file://{self._path(key)}"
