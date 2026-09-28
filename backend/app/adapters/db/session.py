from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.adapters.db.rls import apply_rls
from app.config.models import PlatformSettings
from app.config.secrets import is_secret_ref, resolve_secret
from app.core.context import RequestContext
from app.core.errors import SecretResolutionError

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _use_null_pool() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) or os.environ.get("RAG_DB_NULL_POOL") == "1"


def resolve_database_url(settings: PlatformSettings) -> str:
    url = settings.database.url
    if is_secret_ref(url):
        return resolve_secret(url)
    return url


def init_engine(settings: PlatformSettings) -> AsyncEngine:
    global _engine, _session_factory
    url = resolve_database_url(settings)
    previous = _engine
    if _use_null_pool():
        _engine = create_async_engine(url, pool_pre_ping=True, poolclass=NullPool)
    else:
        _engine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            pool_recycle=1800,
            pool_use_lifo=True,
        )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    if previous is not None and previous is not _engine:
        previous.sync_engine.dispose()
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database engine is not initialized")
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database session factory is not initialized")
    return _session_factory


def try_init_engine(settings: PlatformSettings) -> AsyncEngine | None:
    try:
        return init_engine(settings)
    except (SecretResolutionError, Exception):
        return None


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_session(ctx: RequestContext | None = None) -> AsyncIterator[AsyncSession]:
    factory = session_factory()
    async with factory() as session:
        async with session.begin():
            await apply_rls(session, ctx)
            yield session


def session_dependency(ctx_getter: Callable[..., RequestContext]):
    async def _dep(ctx: RequestContext) -> AsyncIterator[AsyncSession]:
        async for session in get_session(ctx):
            yield session

    return _dep
