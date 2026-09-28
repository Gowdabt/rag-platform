from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from app.core.context import RequestContext
from app.domain.types import (
    ConnectorAuthResult,
    ConnectorDefinition,
    ConnectorFile,
    ConnectorLocation,
    DocumentChange,
)


class DataSourceConnector(ABC):
    """Generic knowledge-source adapter. Provider-specific logic stays in subclasses."""

    definition: ClassVar[ConnectorDefinition]

    def __init__(self, config: dict[str, Any], ctx: RequestContext):
        self.config = config
        self.ctx = ctx

    @abstractmethod
    async def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        raise NotImplementedError

    async def authorization_url(self, *, redirect_uri: str, state: str) -> str | None:
        return None

    async def authenticate(self, credentials: dict[str, Any]) -> ConnectorAuthResult:
        return ConnectorAuthResult(access_token="none", account_label=self.definition.name)

    async def refresh_authentication(self, refresh_token: str) -> ConnectorAuthResult:
        return await self.authenticate({"refresh_token": refresh_token})

    async def list_locations(self, parent_id: str | None = None) -> list[ConnectorLocation]:
        return []

    async def browse(self, location_id: str) -> list[ConnectorLocation | ConnectorFile]:
        return []

    @abstractmethod
    async def list_files(self) -> list[ConnectorFile]:
        raise NotImplementedError

    @abstractmethod
    async def get_file(self, source_file_id: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def get_metadata(self, source_file_id: str) -> ConnectorFile:
        raise NotImplementedError

    @abstractmethod
    async def detect_changes(self, previous: list[ConnectorFile]) -> list[DocumentChange]:
        raise NotImplementedError

    async def health_check(self) -> dict[str, Any]:
        return {"status": "healthy", "provider": self.definition.id}
