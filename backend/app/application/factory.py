from __future__ import annotations

from typing import Any

from app.config.catalog import KNOWN_PROVIDERS
from app.config.models import PlatformSettings
from app.core.context import RequestContext
from app.core.errors import UnknownProviderError
from app.domain.registry import registry


class ProviderFactory:
    """Resolve adapters from effective config. No process-global tenant-ignorant singletons."""

    def __init__(self, settings: PlatformSettings, ctx: RequestContext):
        self.settings = settings
        self.ctx = ctx

    def create(self, kind: str, name: str | None = None, **kwargs: Any) -> Any:
        resolved_name = name or self._default_name(kind)
        known = KNOWN_PROVIDERS.get(kind)
        if known is not None and resolved_name not in known:
            raise UnknownProviderError(
                f"Unknown {kind} provider '{resolved_name}'. Known: {sorted(known)}"
            )
        return registry.create(kind, resolved_name, **kwargs)

    def _default_name(self, kind: str) -> str:
        mapping = {
            "llm": self.settings.llm.provider,
            "embedding": self.settings.embedding.provider,
            "vector_store": self.settings.vector_store.provider,
            "sparse_index": self.settings.sparse_index.provider,
            "reranker": self.settings.reranker.provider,
            "parser": self.settings.parser.provider,
            "chunker": self.settings.chunking.strategy,
            "storage": self.settings.storage.provider,
            "queue": self.settings.queue.provider,
            "ocr": self.settings.ocr.provider,
            "memory": self.settings.memory.provider,
            "auth": self.settings.auth.provider,
            "connector": None,
        }
        if kind not in mapping:
            raise UnknownProviderError(f"Unknown provider kind '{kind}'")
        if mapping[kind] is None:
            raise UnknownProviderError(f"{kind} requires an explicit provider name")
        return mapping[kind]
