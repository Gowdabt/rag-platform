from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.adapters.db.models import ConfigOverlay
from app.application.audit import write_audit
from app.config.catalog import KNOWN_PROVIDERS
from app.config.merge import assert_overlay_allowed, deep_merge
from app.config.models import PlatformSettings
from app.core.context import RequestContext
from app.core.errors import ForbiddenError, ValidationFailedError


def catalog_llm_entries(settings: PlatformSettings) -> list[dict[str, str]]:
    entries = [{"provider": item.provider, "model": item.model} for item in settings.ai_catalog.llm]
    if not entries:
        entries = [{"provider": settings.llm.provider, "model": settings.llm.model}]
        if settings.llm.provider != "extractive":
            entries.append({"provider": "extractive", "model": "extractive"})
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for item in entries:
        key = (item["provider"], item["model"])
        if key in seen:
            continue
        if item["provider"] not in KNOWN_PROVIDERS.get("llm", frozenset()):
            continue
        seen.add(key)
        out.append(item)
    return out


def model_allowed(settings: PlatformSettings, provider: str, model: str) -> bool:
    return any(row["provider"] == provider and row["model"] == model for row in catalog_llm_entries(settings))


def ai_config_payload(settings: PlatformSettings) -> dict:
    return {
        "provider": settings.llm.provider,
        "model": settings.llm.model,
        "temperature": settings.llm.temperature,
        "max_tokens": settings.llm.max_tokens,
        "system_instructions": settings.generation.system_instructions,
        "rag_enabled": settings.generation.rag_enabled,
    }


async def put_ai_config(
    session: AsyncSession,
    ctx: RequestContext,
    platform_settings: PlatformSettings,
    *,
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    system_instructions: str | None = None,
    rag_enabled: bool | None = None,
) -> dict:
    if not ctx.has("tenant.settings.update") and not ctx.has("ai.configuration.update"):
        raise ForbiddenError("Missing permission tenant.settings.update")
    overlay = await session.scalar(
        select(ConfigOverlay).where(
            ConfigOverlay.tenant_id == ctx.tenant_id, ConfigOverlay.scope_type == "tenant"
        )
    )
    current = platform_settings
    if overlay and overlay.payload:
        from app.config.load import parse_settings

        try:
            current = parse_settings(deep_merge(platform_settings.model_dump(), overlay.payload))
        except Exception:
            current = platform_settings
    next_provider = provider if provider is not None else current.llm.provider
    next_model = model if model is not None else current.llm.model
    if not model_allowed(platform_settings, next_provider, next_model):
        raise ValidationFailedError("Model is not in the platform allow-list")
    patch: dict = {"llm": {}, "generation": {}}
    patch["llm"]["provider"] = next_provider
    patch["llm"]["model"] = next_model
    if temperature is not None:
        patch["llm"]["temperature"] = temperature
    if max_tokens is not None:
        patch["llm"]["max_tokens"] = max_tokens
    if system_instructions is not None:
        patch["generation"]["system_instructions"] = system_instructions
    if rag_enabled is not None:
        patch["generation"]["rag_enabled"] = rag_enabled
    if not patch["generation"]:
        patch.pop("generation")
    assert_overlay_allowed(patch, "tenant")
    if overlay is None:
        overlay = ConfigOverlay(
            tenant_id=ctx.require_tenant(),
            scope_type="tenant",
            scope_id=ctx.require_tenant(),
            payload=patch,
            version=1,
        )
        session.add(overlay)
    else:
        overlay.payload = deep_merge(overlay.payload or {}, patch)
        overlay.version += 1
        flag_modified(overlay, "payload")
    await write_audit(
        session,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="ai.config.update",
        resource_type="tenant",
        resource_id=ctx.tenant_id,
        metadata={"provider": next_provider, "model": next_model},
        request_id=ctx.request_id,
    )
    await session.flush()
    from app.config.load import parse_settings

    merged = parse_settings(deep_merge(platform_settings.model_dump(), overlay.payload))
    return ai_config_payload(merged)
