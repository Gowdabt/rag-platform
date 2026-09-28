from __future__ import annotations

import os


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def allow_public_signup() -> bool:
    return _truthy("RAG_ALLOW_PUBLIC_SIGNUP")


def expose_dev_tokens(environment: str) -> bool:
    return environment != "production" or _truthy("RAG_EXPOSE_INVITE_TOKENS")
