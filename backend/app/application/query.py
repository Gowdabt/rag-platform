from __future__ import annotations

import re

_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "be",
    "we", "can", "do", "from", "which", "what", "how", "does", "with", "that", "this",
    "about", "your", "our", "into", "per", "via",
}

_OVERVIEW = re.compile(
    r"\b(intend|purpose|about|overview|this document|what is this|what does this|"
    r"what this|goal of|high[- ]level|summary|scope|what does hld|hld)\b",
    re.I,
)

_CORPUS = re.compile(
    r"\b((how many|howmuch|count|list|which|what)\s+(docs?|documents?|files?|sources?)|"
    r"(docs?|documents?|files?)\s+(do we|we have|have we|are there|indexed)|"
    r"what('?s| is) in (the )?(corpus|index|knowledge base))\b",
    re.I,
)

_PURPOSE = (
    "purpose",
    "intended",
    "intent",
    "overview",
    "introduction",
    "goal",
    "scope",
    "this document",
    "this hld",
    "high-level",
    "problem",
    "objective",
)

FTS_OVERVIEW = "purpose OR overview OR introduction OR goal OR scope OR objective"


def is_overview_question(question: str) -> bool:
    return bool(_OVERVIEW.search(question or ""))


def is_corpus_question(question: str) -> bool:
    return bool(_CORPUS.search(question or ""))


def tokens(text: str) -> set[str]:
    return {
        tok
        for raw in (text or "").lower().split()
        if (tok := raw.strip(".,;:()[]{}\"'")) and len(tok) > 2 and tok not in _STOP
    }


def query_tokens(question: str) -> set[str]:
    base = tokens(question)
    if is_overview_question(question):
        base |= {w for phrase in _PURPOSE for w in tokens(phrase)}
    return base


def is_noise_sentence(text: str) -> bool:
    sent = re.sub(r"\s+", " ", text or "").strip()
    if len(sent) < 24:
        return True
    if sent.count(";") >= 2 or sent.count("/") >= 4:
        return True
    words = sent.split()
    if not words:
        return True
    caps = sum(1 for w in words if w[:1].isupper() and len(w) > 1)
    if len(words) >= 6 and caps / len(words) > 0.55:
        return True
    return False


def lexical_score(query: str, text: str, *, page: int | None = None) -> float:
    qt = query_tokens(query)
    tt = tokens(text)
    if not qt or not tt:
        return 0.0
    overlap = len(qt & tt) / len(qt)
    low = (text or "").lower()
    bonus = 0.0
    if is_overview_question(query):
        bonus += 0.15 * sum(1 for kw in _PURPOSE if kw in low)
        if page is not None and page <= 3:
            bonus += 0.2
    return min(1.0, overlap + bonus)
