from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.adapters.db.session import dispose_engine, try_init_engine
from app.adapters.providers.queues.asyncio_queue import set_job_handler
from app.api.errors import register_exception_handlers
from app.api.frontend import mount_spa
from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.connectors import router as connectors_router
from app.api.v1.documents import router as documents_router
from app.api.v1.eval import router as eval_router
from app.api.v1.folders import router as folders_router
from app.api.v1.health import build_health_router
from app.api.v1.identity import router as identity_router
from app.api.v1.platform import router as platform_router
from app.api.v1.tenant import router as tenant_router
from app.application.jobs import run_ingestion_job
from app.application.providers import load_providers
from app.application.scheduler import scheduler_loop
from app.config.load import load_platform_settings
from app.core.http_security import SecurityHeadersMiddleware
from app.core.logging import RequestIdMiddleware, configure_logging
from app.core.rate_limit import RateLimitMiddleware
from app.core.runtime import enforce_runtime_safety


def create_app() -> FastAPI:
    load_providers()
    settings = load_platform_settings(resolve=False)
    enforce_runtime_safety(settings)
    configure_logging(settings.observability.log_level)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try_init_engine(settings)
        try:
            from app.adapters.db.session import session_factory
            from app.application.identity import IdentityService

            factory = session_factory()
            async with factory() as session:
                async with session.begin():
                    await IdentityService(session, settings).ensure_super_admin()
        except Exception:
            pass

        async def _handler(job_id, job_type, payload, ctx):
            await run_ingestion_job(job_id, settings, ctx)

        set_job_handler(_handler)
        stop = asyncio.Event()
        task = asyncio.create_task(scheduler_loop(settings, stop))
        application.state.scheduler_stop = stop
        yield
        stop.set()
        task.cancel()
        await dispose_engine()

    application = FastAPI(
        title=settings.platform.name,
        version="0.2.0",
        description="Multi-tenant RAG platform",
        lifespan=lifespan,
    )
    application.state.settings = settings
    origins = [item for item in settings.http.cors_origins if str(item).strip() and str(item).strip() != "*"]
    environment = (settings.platform.environment or "").strip().lower()
    cors_kwargs: dict = {
        "allow_origins": origins,
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": ["Authorization", "Content-Type", "Accept"],
    }
    if environment != "production":
        # Vite loopback on any port (not `*` — credentials are enabled).
        cors_kwargs["allow_origin_regex"] = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
    application.add_middleware(RateLimitMiddleware, limit=180, window_seconds=60)
    application.add_middleware(RequestIdMiddleware)
    application.add_middleware(SecurityHeadersMiddleware, environment=settings.platform.environment)
    application.add_middleware(CORSMiddleware, **cors_kwargs)
    register_exception_handlers(application)
    application.include_router(build_health_router(settings))
    application.include_router(auth_router)
    application.include_router(identity_router)
    application.include_router(platform_router)
    application.include_router(tenant_router)
    application.include_router(folders_router)
    application.include_router(documents_router)
    application.include_router(connectors_router)
    application.include_router(chat_router)
    application.include_router(eval_router)
    application.include_router(admin_router)
    mount_spa(application)
    return application


app = create_app()
