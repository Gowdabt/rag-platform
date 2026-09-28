from __future__ import annotations

from pathlib import Path

TEXT_EXTS = {".txt", ".md", ".markdown", ".csv", ".html", ".htm", ".json"}
BINARY_EXTS = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
}
INGEST_EXTS = TEXT_EXTS | BINARY_EXTS

MIME_BY_EXT = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".html": "text/html",
    ".htm": "text/html",
    ".json": "application/json",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def mime_for(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    return MIME_BY_EXT.get(ext, "application/octet-stream")


def ingestible(path: str | Path, mime_type: str | None = None) -> bool:
    ext = Path(path).suffix.lower()
    if ext in INGEST_EXTS:
        return True
    mime = (mime_type or "").lower()
    return mime.startswith("text/") or mime in {
        "application/pdf",
        "application/json",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
