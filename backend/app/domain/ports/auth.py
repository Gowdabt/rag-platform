from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.config.models import AuthConfig
from app.core.context import RequestContext


class AuthProvider(ABC):
    def __init__(self, config: AuthConfig):
        self.config = config

    @abstractmethod
    async def authenticate(self, username: str, password: str) -> UUID:
        raise NotImplementedError

    @abstractmethod
    async def issue_tokens(self, user_id: UUID, tenant_id: UUID) -> dict[str, str]:
        raise NotImplementedError

    @abstractmethod
    async def authenticate_request(self, token: str) -> RequestContext:
        raise NotImplementedError
