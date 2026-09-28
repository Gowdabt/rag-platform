import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config.models import PlatformSettings


def build_health_router(settings: PlatformSettings) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/health/live")
    async def live() -> dict:
        return {"status": "ok"}

    @router.get("/health/ready", response_model=None)
    async def ready():
        from app.adapters.db.session import session_factory

        try:
            factory = session_factory()
            async with factory() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return {"status": "ok"}

    @router.get("/health")
    async def health() -> dict:
        ollama = await _ollama_status(settings)
        status = "ok" if ollama["reachable"] else "degraded"
        return {
            "status": status,
            "environment": settings.platform.environment,
            "name": settings.platform.name,
            "providers": {
                "llm": settings.llm.provider,
                "llm_model": settings.llm.model,
                "embedding": settings.embedding.provider,
                "embedding_model": settings.embedding.model,
                "vector_store": settings.vector_store.provider,
                "sparse_index": settings.sparse_index.provider,
                "reranker": settings.reranker.provider,
            },
            "ollama": ollama,
        }

    return router


async def _ollama_status(settings: PlatformSettings) -> dict:
    base = (settings.llm.api_base or "http://127.0.0.1:11434").rstrip("/")
    if base.startswith("secret://"):
        base = "http://127.0.0.1:11434"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{base}/api/tags")
            resp.raise_for_status()
            names = [m.get("name", "") for m in resp.json().get("models", [])]
        llm_ok = any(settings.llm.model in name for name in names)
        emb_ok = settings.embedding.provider != "ollama" or any(
            settings.embedding.model in name for name in names
        )
        return {
            "reachable": True,
            "llm_model_present": llm_ok,
            "embedding_model_present": emb_ok,
        }
    except Exception:
        return {
            "reachable": False,
            "llm_model_present": False,
            "embedding_model_present": False,
        }
