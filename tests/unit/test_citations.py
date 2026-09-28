from app.application.chat import _citations_for, _validate_citations

SOURCES = [
    {"index": 1, "chunk_id": "c1", "document_name": "handbook.txt"},
    {"index": 2, "chunk_id": "c2", "document_name": "policy.md"},
]


def test_validate_keeps_only_retrieved_indexes():
    text = "Full-time employees get 15 days [1]."
    assert _validate_citations(text, SOURCES) == [SOURCES[0]]


def test_invented_citation_ids_are_dropped():
    text = "Secret salary is $1M [99]."
    assert _validate_citations(text, SOURCES) == []
    assert _citations_for(text, SOURCES) == []


def test_uncited_answer_falls_back_to_retrieved_sources():
    text = "Full-time employees receive fifteen days of PTO."
    cited = _citations_for(text, SOURCES)
    assert cited == SOURCES[:2]


def test_mixed_real_and_invented_keeps_only_real():
    text = "PTO is 15 days [1] and also [77]."
    assert _citations_for(text, SOURCES) == [SOURCES[0]]
