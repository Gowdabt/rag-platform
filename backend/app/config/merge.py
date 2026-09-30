from __future__ import annotations

from typing import Any

from app.core.errors import OverlayDeniedError

USER_ALLOWLIST = frozenset(
    {
        "llm.temperature",
        "llm.max_tokens",
        "retrieval.top_k",
        "retrieval.dense.top_k",
        "retrieval.sparse.top_k",
        "conversation.max_history_messages",
    }
)

REQUEST_ALLOWLIST = frozenset(
    {
        "llm.temperature",
        "retrieval.top_k",
    }
)

ALWAYS_DENIED_PATHS = frozenset(
    {
        "tenant_id",
    }
)

ALWAYS_DENIED_PREFIXES = (
    "database.",
    "redis.",
    "http.",
    "auth.jwt_secret",
    "auth.provider",
    "llm.api_key",
    "embedding.api_key",
    "vector_store.api_key",
    "storage.access_key",
    "storage.secret_key",
    "email.",
)

USER_REQUEST_DENIED_PREFIXES = (
    "llm.provider",
    "embedding.provider",
    "embedding.model",
    "vector_store.",
    "sparse_index.",
    "parser.",
    "chunking.",
    "reranker.provider",
    "storage.",
    "queue.",
    "privacy.",
    "limits.monthly_budget_usd",
    "database.",
    "memory.enabled",
    "ocr.",
    "model_routing.",
    "email.",
)


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def leaf_paths(data: dict[str, Any], prefix: str = "") -> list[str]:
    paths: list[str] = []
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            if value:
                paths.extend(leaf_paths(value, path))
            else:
                paths.append(path)
        else:
            paths.append(path)
    return paths


def _denied(path: str, prefixes: tuple[str, ...], exact: frozenset[str]) -> bool:
    if path in exact:
        return True
    return any(path == p or path.startswith(p) for p in prefixes)


def assert_overlay_allowed(overlay: dict[str, Any], scope: str) -> None:
    """Reject overlays that would bypass security or tenant isolation."""
    paths = leaf_paths(overlay)
    for path in paths:
        if _denied(path, ALWAYS_DENIED_PREFIXES, ALWAYS_DENIED_PATHS):
            raise OverlayDeniedError(f"Overlay key '{path}' is not allowed at any overlay scope")

    if scope in {"user", "request"}:
        allow = REQUEST_ALLOWLIST if scope == "request" else USER_ALLOWLIST
        for path in paths:
            if _denied(path, USER_REQUEST_DENIED_PREFIXES, frozenset()):
                raise OverlayDeniedError(
                    f"Overlay key '{path}' cannot be set at {scope} scope"
                )
            if path not in allow:
                raise OverlayDeniedError(
                    f"Overlay key '{path}' is not in the {scope} allowlist"
                )
