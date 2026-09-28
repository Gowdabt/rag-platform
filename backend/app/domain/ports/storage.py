from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import timedelta

from app.config.models import StorageConfig
from app.core.context import RequestContext


class ObjectStore(ABC):
    def __init__(self, config: StorageConfig, ctx: RequestContext):
        self.config = config
        self.ctx = ctx

    @abstractmethod
    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        raise NotImplementedError

    @abstractmethod
    async def get(self, key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def signed_url(self, key: str, *, expires: timedelta = timedelta(minutes=15)) -> str:
        raise NotImplementedError
