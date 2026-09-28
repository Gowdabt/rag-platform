from __future__ import annotations

import re
from collections.abc import AsyncIterator

from app.application.query import is_noise_sentence, is_overview_question, lexical_score
from app.config.models import LLMConfig
from app.core.context import RequestContext
from app.domain.ports.llm import LLMProvider
from app.domain.registry import register
from app.domain.types import LLMGenerateRequest, LLMGenerateResult, TokenUsage

_SOURCE_BLOCK = re.compile(r"\[(\d+)\]\s+([^\n]+)\n(.*?)(?=\n\[\d+\]\s|\Z)", re.S)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_PAGE = re.compile(r"p\.(\d+)")


@register("llm", "extractive")
class ExtractiveLLM(LLMProvider):
    """Grounded extractive answers from retrieved chunks. No external model call."""

    def __init__(self, config: LLMConfig, ctx: RequestContext):
        super().__init__(config, ctx)

    async def generate(self, request: LLMGenerateRequest) -> LLMGenerateResult:
        text = answer_from_sources(request)
        return LLMGenerateResult(text=text, model="extractive", provider="extractive", usage=TokenUsage())

    async def stream(self, request: LLMGenerateRequest) -> AsyncIterator[str]:
        yield answer_from_sources(request)


def answer_from_sources(request: LLMGenerateRequest) -> str:
    system = next((m.content for m in request.messages if m.role == "system"), "")
    users = [m.content for m in request.messages if m.role == "user"]
    question = " ".join(users[-3:]) if users else ""
    blob = system.split("SOURCES:", 1)[1] if "SOURCES:" in system else system
    sources = _parse_sources(blob)
    if not sources:
        return _from_context(request)

    scored: list[tuple[float, str, int]] = []
    for src in sources:
        repaired = _repair_lines(src["text"])
        page = _page(src["label"])
        for sent in _sentences(repaired):
            if is_noise_sentence(sent):
                continue
            score = lexical_score(question, sent, page=page)
            if score <= 0:
                continue
            scored.append((score, sent, src["index"]))
    scored.sort(key=lambda item: item[0], reverse=True)

    picked: list[tuple[str, int]] = []
    seen: set[str] = set()
    for score, sent, idx in scored:
        if score < 0.08 and not is_overview_question(question):
            continue
        key = sent.lower()
        if key in seen:
            continue
        seen.add(key)
        picked.append((sent, idx))
        if len(picked) >= 3:
            break

    if not picked and sources:
        fallback = _best_intro(sources, question)
        if fallback:
            picked = [fallback]

    if not picked:
        return (
            "I couldn't find a passage that answers that. Try asking about a specific section, "
            "API, or term from the document."
        )

    lines = [f"{sent} [{idx}]" for sent, idx in picked]
    cited = sorted({idx for _sent, idx in picked})
    labels = {s["index"]: src_label(s["label"]) for s in sources}
    footer = "\n".join(f"[{i}] {labels.get(i, 'source')}" for i in cited)
    return "\n\n".join(lines) + "\n\nSources\n" + footer


def src_label(label: str) -> str:
    return label.replace(" p.?", "").strip()


def _page(label: str) -> int | None:
    match = _PAGE.search(label or "")
    return int(match.group(1)) if match else None


def _best_intro(sources: list[dict], question: str) -> tuple[str, int] | None:
    ranked = []
    for src in sources:
        page = _page(src["label"]) or 99
        for sent in _sentences(_repair_lines(src["text"])):
            if is_noise_sentence(sent):
                continue
            ranked.append((page, -lexical_score(question, sent, page=page), sent, src["index"]))
    ranked.sort()
    if not ranked:
        return None
    _page_n, _score, sent, idx = ranked[0]
    return sent, idx


def _parse_sources(blob: str) -> list[dict]:
    found = []
    for match in _SOURCE_BLOCK.finditer(blob.strip()):
        found.append({"index": int(match.group(1)), "label": match.group(2).strip(), "text": match.group(3).strip()})
    if found:
        return found
    text = blob.strip()
    if text:
        return [{"index": 1, "label": "document", "text": text}]
    return []


def _repair_lines(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    merged: list[str] = [lines[0]]
    for line in lines[1:]:
        prev = merged[-1]
        next_is_sentence = line[:1].isupper() and len(line) >= 40
        if len(prev) < 80 and not prev.endswith((".", "?", "!", ":", ";")) and not next_is_sentence:
            joiner = "" if prev.endswith("-") else " "
            merged[-1] = prev + joiner + line
        else:
            merged.append(line)
    return "\n".join(merged)


def _sentences(text: str) -> list[str]:
    out = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        parts = _SENTENCE.split(para) if re.search(r"[.!?]", para) else [para]
        for part in parts:
            cleaned = re.sub(r"\s+", " ", part).strip()
            if len(cleaned) >= 24:
                out.append(cleaned)
    return out or ([re.sub(r"\s+", " ", text).strip()] if text.strip() else [])


def _from_context(request: LLMGenerateRequest) -> str:
    user = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
    return user
