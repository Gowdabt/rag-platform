from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def frontend_dist() -> Path | None:
    raw = os.environ.get("RAG_FRONTEND_DIST", "").strip()
    candidates: list[Path] = []
    if raw:
        candidates.append(Path(raw).expanduser())
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / "frontend" / "dist")
    for path in candidates:
        if (path / "index.html").is_file():
            return path.resolve()
    return None


def mount_spa(application: FastAPI) -> None:
    if os.environ.get("RAG_SERVE_FRONTEND", "").lower() not in {"1", "true", "yes"}:
        return
    dist = frontend_dist()
    if dist is None:
        return
    assets = dist / "assets"
    if assets.is_dir():
        application.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

    @application.get("/")
    async def spa_root() -> FileResponse:
        return FileResponse(dist / "index.html")

    @application.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = dist / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")
