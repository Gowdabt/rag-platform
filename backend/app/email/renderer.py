from __future__ import annotations

import html
import re
from pathlib import Path

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_TEMPLATES = Path(__file__).resolve().parent / "templates"


class UnknownEmailTemplateError(ValueError):
    pass


def render_template(name: str, data: dict[str, str]) -> tuple[str, str, str]:
    """Return (subject, text, html). Interpolated values are HTML-escaped in HTML files."""
    root = _TEMPLATES / name
    if not root.is_dir():
        raise UnknownEmailTemplateError(f"Unknown email template '{name}'")
    subject_src = (root / "subject.txt").read_text(encoding="utf-8").strip()
    text_src = (root / "body.txt").read_text(encoding="utf-8")
    html_src = (root / "body.html").read_text(encoding="utf-8")
    safe_html = {key: html.escape(str(value), quote=True) for key, value in data.items()}
    plain = {key: str(value) for key, value in data.items()}
    return (
        _substitute(subject_src, plain).strip(),
        _substitute(text_src, plain),
        _substitute(html_src, safe_html),
    )


def _substitute(source: str, data: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in data:
            raise UnknownEmailTemplateError(f"Missing template data '{key}'")
        return data[key]

    return _PLACEHOLDER.sub(repl, source)
