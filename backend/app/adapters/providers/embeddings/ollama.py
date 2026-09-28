from __future__ import annotations

import httpx

from app.config.models import EmbeddingConfig
from app.core.context import RequestContext
from app.core.errors import PlatformError
from app.domain.ports.embeddings import EmbeddingProvider
from app.domain.registry import register
from app.domain.types import EmbeddingResult


@register("embedding", "ollama")
class OllamaEmbedding(EmbeddingProvider):
    def __init__(self, config: EmbeddingConfig, ctx: RequestContext):
        super().__init__(config, ctx)

    def _base(self) -> str:
        return "http://127.0.0.1:11434"

    async def embed_documents(self, texts: list[str]) -> EmbeddingResult:
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=120.0) as client:
            for text in texts:
                try:
                    resp = await client.post(
                        f"{self._base()}/api/embeddings",
                        json={"model": self.config.model, "prompt": text},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    vectors.append(data["embedding"])
                except httpx.ConnectError as exc:
                    raise PlatformError(
                        f"Ollama is not running at {self._base()}. Start it with `ollama serve` and pull `{self.config.model}`.",
                        status_code=502,
                    ) from exc
                except httpx.HTTPError as exc:
                    raise PlatformError(f"Ollama embedding failed: {exc}", status_code=502) from exc
        dim = self.config.dimensions or (len(vectors[0]) if vectors else 0)
        return EmbeddingResult(
            vectors=vectors, model=self.config.model, provider="ollama", dimensions=dim, version="1"
        )

    async def embed_query(self, text: str) -> EmbeddingResult:
        return await self.embed_documents([text])


@register("embedding", "openai")
@register("embedding", "openai_compatible")
class OpenAIEmbedding(EmbeddingProvider):
    def __init__(self, config: EmbeddingConfig, ctx: RequestContext):
        super().__init__(config, ctx)

    async def embed_documents(self, texts: list[str]) -> EmbeddingResult:

        base = "https://api.openai.com/v1"
        headers = {"Content-Type": "application/json"}
        if self.config.model:
            pass
        # api key is not on EmbeddingConfig; optional env OPENAI_API_KEY
        import os

        key = os.environ.get("OPENAI_API_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                resp = await client.post(
                    f"{base}/embeddings",
                    json={"model": self.config.model, "input": texts},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                vectors = [item["embedding"] for item in data["data"]]
            except httpx.HTTPError as exc:
                raise PlatformError(f"OpenAI embedding failed: {exc}", status_code=502) from exc
        dim = self.config.dimensions or (len(vectors[0]) if vectors else 0)
        return EmbeddingResult(
            vectors=vectors, model=self.config.model, provider="openai", dimensions=dim, version="1"
        )

    async def embed_query(self, text: str) -> EmbeddingResult:
        return await self.embed_documents([text])
