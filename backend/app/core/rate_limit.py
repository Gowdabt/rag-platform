from __future__ import annotations

import os
import time
from collections import defaultdict
from datetime import UTC, datetime

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_AUTH_SUFFIXES = frozenset(
    {
        "login",
        "signup",
        "accept-invite",
        "forgot-password",
        "reset-password",
        "refresh",
    }
)

_RATE_UPSERT = """
INSERT INTO rate_limit_buckets (bucket_key, window_started_at, hit_count)
VALUES (:key, :window_started_at, 1)
ON CONFLICT (bucket_key, window_started_at)
DO UPDATE SET hit_count = rate_limit_buckets.hit_count + 1
RETURNING hit_count
"""


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-process limiter plus a PostgreSQL counter shared across workers.

    Auth (login/signup/...) stays IP-only and uses RAG_AUTH_RATE_LIMIT (default 10/min).
    General API keys include IP and tenant when a valid access token is present.
    Redis is not required; multi-replica accuracy comes from the shared DB table.
    """

    def __init__(self, app, *, limit: int = 120, window_seconds: int = 60):
        super().__init__(app)
        self.limit = limit
        self.window = window_seconds
        self.auth_limit = int(os.environ.get("RAG_AUTH_RATE_LIMIT", "10"))
        self.auth_window = int(os.environ.get("RAG_AUTH_RATE_WINDOW", "60"))
        self._hits: dict[str, list[float]] = defaultdict(list)

    def _is_auth_path(self, path: str) -> bool:
        if not path.startswith("/api/v1/auth/"):
            return False
        return path.rstrip("/").rsplit("/", 1)[-1] in _AUTH_SUFFIXES

    def _client_ip(self, request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def _tenant_hint(self, request: Request) -> str:
        header = request.headers.get("authorization") or ""
        if not header.lower().startswith("bearer "):
            return "-"
        token = header.split(" ", 1)[1].strip()
        settings = getattr(request.app.state, "settings", None)
        if settings is None or not token:
            return "-"
        try:
            from app.core.security import decode_jwt, resolve_jwt_secret

            claims = decode_jwt(token, resolve_jwt_secret(settings.auth.jwt_secret), expected_type="access")
            tid = claims.get("tid")
            return str(tid) if tid else "-"
        except Exception:
            return "-"

    def _bucket_key(self, request: Request, *, auth_path: bool) -> str:
        ip = self._client_ip(request)
        if auth_path:
            return f"{ip}:auth"
        return f"{ip}:api:{self._tenant_hint(request)}"

    async def _shared_hit(self, bucket_key: str, window: int) -> int | None:
        if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get("RAG_RATE_LIMIT_DB") != "1":
            return None
        try:
            from sqlalchemy import text

            from app.adapters.db.session import session_factory

            factory = session_factory()
        except Exception:
            return None
        now = time.time()
        window_start = int(now // window) * window
        started = datetime.fromtimestamp(window_start, tz=UTC)
        try:
            async with factory() as session:
                async with session.begin():
                    await session.execute(
                        text("DELETE FROM rate_limit_buckets WHERE bucket_key = :key AND window_started_at < :window_started_at"),
                        {"key": bucket_key, "window_started_at": started},
                    )
                    count = await session.scalar(
                        text(_RATE_UPSERT),
                        {"key": bucket_key, "window_started_at": started},
                    )
                    return int(count or 0)
        except Exception:
            return None

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path.startswith("/api/v1/health"):
            return await call_next(request)
        now = time.time()
        auth_path = self._is_auth_path(request.url.path)
        limit = self.auth_limit if auth_path else self.limit
        window = self.auth_window if auth_path else self.window
        bucket_key = self._bucket_key(request, auth_path=auth_path)
        bucket = self._hits[bucket_key]
        self._hits[bucket_key] = [t for t in bucket if now - t < window]
        if len(self._hits[bucket_key]) >= limit:
            return self._reject()
        shared = await self._shared_hit(bucket_key, window)
        if shared is not None and shared > limit:
            return self._reject()
        self._hits[bucket_key].append(now)
        return await call_next(request)

    def _reject(self) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "type": "about:blank",
                "title": "Too Many Requests",
                "status": 429,
                "detail": "Rate limit exceeded",
                "code": "rate_limited",
            },
        )
