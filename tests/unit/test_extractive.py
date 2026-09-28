from app.adapters.providers.llm.extractive import answer_from_sources
from app.domain.types import LLMGenerateRequest, LLMMessage


def test_extractive_picks_relevant_sentence_not_full_dump():
    request = LLMGenerateRequest(
        messages=[
            LLMMessage(
                role="system",
                content=(
                    "You are a document-grounded assistant.\n\nSOURCES:\n"
                    "[1] HLD.docx.pdf p.10\n"
                    "Type Metadata Conversation pattern Parse strategy Notes\n"
                    "Full-time employees receive fifteen days of paid time off each year.\n"
                    "[2] other.pdf p.1\n"
                    "Unrelated networking configuration details."
                ),
            ),
            LLMMessage(role="user", content="How many PTO days do employees get?"),
        ]
    )
    answer = answer_from_sources(request)
    assert "fifteen days" in answer.lower()
    assert "Type Metadata Conversation pattern" not in answer
    assert "[1]" in answer


def test_extractive_overview_prefers_purpose_not_api_fragments():
    request = LLMGenerateRequest(
        messages=[
            LLMMessage(
                role="system",
                content=(
                    "SOURCES:\n"
                    "[6] HLD.docx.pdf p.15\n"
                    "dashboards; feature flags per channel/AI; backward-compat test against multiple flow API\n"
                    "[1] HLD.docx.pdf p.1\n"
                    "This document describes a headless, turn-by-turn flow interview runtime for Salesforce.\n"
                    "[7] HLD.docx.pdf p.3\n"
                    "API selection (Part 12 — summary); full matrix in api-selection.md"
                ),
            ),
            LLMMessage(role="user", content="what this document intended to do"),
        ]
    )
    answer = answer_from_sources(request)
    assert "interview runtime" in answer.lower() or "this document describes" in answer.lower()
    assert "feature flags per channel" not in answer


def test_extractive_uses_prior_user_turn_for_follow_up():
    request = LLMGenerateRequest(
        messages=[
            LLMMessage(
                role="system",
                content=(
                    "SOURCES:\n[1] api.md p.2\n"
                    "Headless navigation is available through the Conversation Runtime API."
                ),
            ),
            LLMMessage(role="user", content="How does headless navigation work?"),
            LLMMessage(role="assistant", content="It is driven by the runtime."),
            LLMMessage(role="user", content="from which api can we do that"),
        ]
    )
    answer = answer_from_sources(request)
    assert "Conversation Runtime API" in answer
