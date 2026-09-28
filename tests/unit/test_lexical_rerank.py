from uuid import uuid4

from app.adapters.providers.rerankers.lexical import LexicalReranker
from app.application.query import is_corpus_question, is_overview_question, lexical_score
from app.config.models import RerankerConfig
from app.core.context import RequestContext
from app.domain.types import RerankCandidate


def test_overview_question_detected():
    assert is_overview_question("what this document intended to do")
    assert is_overview_question("what does hld has")
    assert not is_overview_question("from which api can we do headless navigation")


def test_corpus_question_detected():
    assert is_corpus_question("how many docs we have")
    assert is_corpus_question("list documents")
    assert not is_corpus_question("what is the PTO policy")


def test_lexical_score_prefers_purpose_sentence():
    query = "what this document intended to do"
    purpose = "This document describes a headless interview runtime."
    noise = "dashboards; feature flags per channel/AI; backward-compat test"
    assert lexical_score(query, purpose, page=1) > lexical_score(query, noise, page=15)


async def test_lexical_reranker_orders_purpose_first():
    rerank = LexicalReranker(RerankerConfig(provider="lexical", top_k=2), RequestContext(request_id="t"))
    ranked = await rerank.rerank(
        "what this document intended to do",
        [
            RerankCandidate(chunk_id=uuid4(), text="API selection matrix", score=0.9, payload={"page": 15}),
            RerankCandidate(
                chunk_id=uuid4(),
                text="This document describes the conversation runtime purpose and scope.",
                score=0.1,
                payload={"page": 1},
            ),
        ],
    )
    assert "purpose and scope" in ranked[0].text
