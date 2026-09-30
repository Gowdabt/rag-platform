from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import PlatformError


def problem(status: int, title: str, detail: str, code: str, request_id: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
    }
    if request_id:
        body["request_id"] = request_id
    return body


def format_validation_detail(errors: list[Any]) -> str:
    """Human-readable 422 detail from Pydantic/FastAPI error dicts. Omits raw input (may contain secrets)."""
    parts: list[str] = []
    for err in errors:
        if not isinstance(err, dict):
            continue
        loc = [str(part) for part in err.get("loc", ()) if part not in {"body", "query", "path", "header"}]
        msg = str(err.get("msg") or "Invalid value")
        parts.append(f"{'.'.join(loc)}: {msg}" if loc else msg)
    return "; ".join(parts) or "Request validation failed"


def validation_error_items(errors: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for err in errors:
        if not isinstance(err, dict):
            continue
        items.append(
            {
                "loc": [str(part) for part in err.get("loc", ())],
                "msg": str(err.get("msg") or "Invalid value"),
                "type": str(err.get("type") or ""),
            }
        )
    return items


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(PlatformError)
    async def platform_error(request: Request, exc: PlatformError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        titles = {
            400: "Bad Request",
            401: "Unauthorized",
            402: "Payment Required",
            403: "Forbidden",
            404: "Not Found",
            409: "Conflict",
            422: "Unprocessable Entity",
            429: "Too Many Requests",
            500: "Internal Server Error",
            501: "Not Implemented",
        }
        return JSONResponse(
            status_code=exc.status_code,
            content=problem(
                exc.status_code,
                titles.get(exc.status_code, "Error"),
                str(exc),
                exc.code,
                request_id,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        raw = exc.errors()
        content = problem(422, "Unprocessable Entity", format_validation_detail(raw), "validation_error", request_id)
        content["errors"] = validation_error_items(raw)
        return JSONResponse(status_code=422, content=content)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=500,
            content=problem(500, "Internal Server Error", "An unexpected error occurred", "platform_error", request_id),
        )
