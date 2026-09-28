from __future__ import annotations

import re

_TAG = re.compile(r"<[^>]*>")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def untrusted_text(value: object, *, max_len: int = 2048) -> str:
    """Strip HTML/control chars from retrieved or user-controlled display strings."""
    if value is None:
        return ""
    text = _CTRL.sub("", _TAG.sub("", str(value)))
    if len(text) > max_len:
        return text[:max_len]
    return text
