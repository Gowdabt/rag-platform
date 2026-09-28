from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.config.models import LLMConfig
from app.core.context import RequestContext
from app.domain.types import LLMGenerateRequest, LLMGenerateResult


class LLMProvider(ABC):
    def __init__(self, config: LLMConfig, ctx: RequestContext):
        self.config = config
        self.ctx = ctx

    @abstractmethod
    async def generate(self, request: LLMGenerateRequest) -> LLMGenerateResult:
        raise NotImplementedError

    @abstractmethod
    async def stream(self, request: LLMGenerateRequest) -> AsyncIterator[str]:
        raise NotImplementedError
        yield  # pragma: no cover — keeps this a generator for type checkers
