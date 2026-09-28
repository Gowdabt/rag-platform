from __future__ import annotations

DEFAULT_LIMIT = 100
MAX_LIMIT = 100


def clip_limit(limit: int | None, *, default: int = DEFAULT_LIMIT, maximum: int = MAX_LIMIT) -> int:
    if limit is None:
        return default
    return max(1, min(int(limit), maximum))


def clip_offset(offset: int | None) -> int:
    if offset is None:
        return 0
    return max(0, int(offset))
