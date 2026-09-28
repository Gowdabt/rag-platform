from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from app.config.models import LLMConfig
from app.config.secrets import is_secret_ref, resolve_secret
from app.core.context import RequestContext
from app.core.errors import PlatformError, SecretResolutionError
from app.domain.ports.llm import LLMProvider
from app.domain.registry import register
from app.domain.types import LLMGenerateRequest, LLMGenerateResult, TokenUsage


@register("llm", "ollama")
class OllamaLLM(LLMProvider):
    def __init__(self, config: LLMConfig, ctx: RequestContext):
        super().__init__(config, ctx)

    def _base(self) -> str:
        raw = self.config.api_base or "http://127.0.0.1:11434"
        if is_secret_ref(raw):
            try:
                raw = resolve_secret(raw)
            except SecretResolutionError:
                raw = "http://127.0.0.1:11434"
        return raw.rstrip("/")

    async def generate(self, request: LLMGenerateRequest) -> LLMGenerateResult:
        text = ""
        async for part in self.stream(request):
            text += part
        return LLMGenerateResult(
            text=text,
            model=self.config.model,
            provider="ollama",
            usage=TokenUsage(),
        )

    async def stream(self, request: LLMGenerateRequest) -> AsyncIterator[str]:
        payload = {
            "model": self.config.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": True,
            "options": {
                "temperature": request.temperature if request.temperature is not None else self.config.temperature,
                "num_predict": request.max_tokens or self.config.max_tokens,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream("POST", f"{self._base()}/api/chat", json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        import json

                        data = json.loads(line)
                        msg = data.get("message") or {}
                        chunk = msg.get("content") or ""
                        if chunk:
                            yield chunk
        except httpx.ConnectError as exc:
            raise PlatformError(
                f"Ollama is not running at {self._base()}. Start it with `ollama serve` and pull `{self.config.model}`.",
                status_code=502,
            ) from exc
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                raise PlatformError(
                    f"Ollama model `{self.config.model}` is not available. Run `ollama pull {self.config.model}`.",
                    status_code=502,
                ) from exc
            raise PlatformError(f"Ollama request failed: {exc}", status_code=502) from exc
        except httpx.HTTPError as exc:
            raise PlatformError(f"Ollama request failed: {exc}", status_code=502) from exc
