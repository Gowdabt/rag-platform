from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.db.rls import apply_rls
from app.adapters.db.session import session_factory
from app.api.deps import get_context, get_tenant_settings, require_permission
from app.application.chat import ChatService
from app.config.models import PlatformSettings
from app.core.context import RequestContext

router = APIRouter(prefix="/api/v1", tags=["chat"])


class ChatIn(BaseModel):
    question: str
    conversation_id: UUID | None = None
    workspace_id: UUID | None = None
    version_id: UUID | None = None


class FeedbackIn(BaseModel):
    rating: str
    reason: str | None = None


async def _db(ctx: RequestContext = Depends(get_context)) -> AsyncSession:
    factory = session_factory()
    async with factory() as session:
        async with session.begin():
            await apply_rls(session, ctx)
            yield session


@router.post("/chat")
async def chat(
    body: ChatIn,
    ctx: RequestContext = Depends(require_permission("document:read")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await ChatService(session, settings, ctx).ask(
        question=body.question,
        conversation_id=body.conversation_id,
        workspace_id=body.workspace_id,
        version_id=body.version_id,
    )


@router.post("/chat/stream")
async def chat_stream(
    body: ChatIn,
    ctx: RequestContext = Depends(require_permission("document:read")),
    settings: PlatformSettings = Depends(get_tenant_settings),
):
    factory = session_factory()
    async with factory() as session:
        async with session.begin():
            await apply_rls(session, ctx)
            await ChatService(session, settings, ctx).authorize_ask(
                conversation_id=body.conversation_id,
                workspace_id=body.workspace_id,
                version_id=body.version_id,
            )

    async def events():
        inner = session_factory()
        async with inner() as session:
            await apply_rls(session, ctx)
            async for payload in ChatService(session, settings, ctx).stream_ask(
                question=body.question,
                conversation_id=body.conversation_id,
                workspace_id=body.workspace_id,
                version_id=body.version_id,
            ):
                event = json.loads(payload)
                if event.get("event") == "generation.completed":
                    # Commit before the client is told the message exists, otherwise
                    # the UI reload races an uncommitted transaction.
                    await session.commit()
                yield f"data: {payload}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/conversations")
async def conversations(
    ctx: RequestContext = Depends(require_permission("conversation:read")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await ChatService(session, settings, ctx).list_conversations(limit=limit, offset=offset)


@router.delete("/conversations")
async def delete_all_conversations(
    ctx: RequestContext = Depends(require_permission("conversation:delete")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await ChatService(session, settings, ctx).delete_all_conversations()


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: UUID,
    ctx: RequestContext = Depends(require_permission("conversation:delete")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await ChatService(session, settings, ctx).delete_conversation(conversation_id)


@router.get("/conversations/{conversation_id}")
async def conversation_messages(
    conversation_id: UUID,
    ctx: RequestContext = Depends(require_permission("conversation:read")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await ChatService(session, settings, ctx).get_messages(conversation_id)


@router.post("/messages/{message_id}/feedback")
async def feedback(
    message_id: UUID,
    body: FeedbackIn,
    ctx: RequestContext = Depends(get_context),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await ChatService(session, settings, ctx).feedback(message_id, rating=body.rating, reason=body.reason)
