from __future__ import annotations

import re

_SLUG = re.compile(r"[^a-z0-9-]+")


def slugify(value: str) -> str:
    slug = _SLUG.sub("-", value.strip().lower()).strip("-")
    return slug[:128] or "item"
