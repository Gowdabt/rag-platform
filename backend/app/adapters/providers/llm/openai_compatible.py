from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from app.config.models import LLMConfig
from app.core.context import RequestContext
from app.core.errors import PlatformError
from app.domain.ports.llm import LLMProvider
from app.domain.registry import register
from app.domain.types import LLMGenerateRequest, LLMGenerateResult, TokenUsage


class OpenAICompatibleLLM(LLMProvider):
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            from app.config.secrets import is_secret_ref, resolve_secret

            key = resolve_secret(self.config.api_key) if is_secret_ref(self.config.api_key) else self.config.api_key
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _base(self) -> str:
        return (self.config.api_base or "https://api.openai.com/v1").rstrip("/")

    async def generate(self, request: LLMGenerateRequest) -> LLMGenerateResult:
        text = "".join([p async for part in self.stream(request) for p in [part]])
        return LLMGenerateResult(
            text=text, model=self.config.model, provider=self.config.provider, usage=TokenUsage()
        )

    async def stream(self, request: LLMGenerateRequest) -> AsyncIterator[str]:
        payload = {
            "model": self.config.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": True,
            "temperature": request.temperature if request.temperature is not None else self.config.temperature,
            "max_tokens": request.max_tokens or self.config.max_tokens,
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST", f"{self._base()}/chat/completions", json=payload, headers=self._headers()
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            break
                        import json

                        chunk = json.loads(data)
                        delta = (((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content")) or ""
                        if delta:
                            yield delta
        except httpx.HTTPError as exc:
            raise PlatformError(f"OpenAI-compatible request failed: {exc}", status_code=502) from exc


@register("llm", "openai")
class OpenAILLM(OpenAICompatibleLLM):
    def __init__(self, config: LLMConfig, ctx: RequestContext):
        super().__init__(config, ctx)

    def _base(self) -> str:
        return (self.config.api_base or "https://api.openai.com/v1").rstrip("/")


@register("llm", "openai_compatible")
class GenericOpenAICompatibleLLM(OpenAICompatibleLLM):
    pass


@register("llm", "vllm")
class VLLMLLM(OpenAICompatibleLLM):
    pass
