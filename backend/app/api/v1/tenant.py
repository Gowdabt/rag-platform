from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.db.rls import apply_rls
from app.adapters.db.session import session_factory
from app.api.deps import get_context, get_settings, get_tenant_settings, require_any_permission
from app.application.tenant_ai import ai_config_payload, put_ai_config
from app.config.models import PlatformSettings
from app.core.context import RequestContext


class AIConfigIn(BaseModel):
    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    system_instructions: str | None = None
    rag_enabled: bool | None = None


router = APIRouter(prefix="/api/v1/tenant", tags=["tenant"])


async def _db(ctx: RequestContext = Depends(get_context)) -> AsyncSession:
    factory = session_factory()
    async with factory() as session:
        async with session.begin():
            await apply_rls(session, ctx)
            yield session


@router.get("/ai-config")
async def get_ai_config(
    ctx: RequestContext = Depends(
        require_any_permission("ai.configuration.view", "tenant.settings.view", "config:read")
    ),
    settings: PlatformSettings = Depends(get_tenant_settings),
):
    return ai_config_payload(settings)


@router.put("/ai-config")
async def update_ai_config(
    body: AIConfigIn,
    ctx: RequestContext = Depends(
        require_any_permission("ai.configuration.update", "tenant.settings.update", "config:write")
    ),
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_db),
):
    return await put_ai_config(
        session,
        ctx,
        settings,
        provider=body.provider,
        model=body.model,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        system_instructions=body.system_instructions,
        rag_enabled=body.rag_enabled,
    )
