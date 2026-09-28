from app.application.eval import citation_recall, lexical_f1, score_item


def test_lexical_f1_perfect_match():
    assert lexical_f1("paid time off", "Paid time off") == 1.0


def test_lexical_f1_empty_expected_is_one():
    assert lexical_f1(None, "anything") == 1.0
    assert lexical_f1("", "anything") == 1.0


def test_citation_recall_matches_document_name():
    expected = [{"document_name": "leave-policy.pdf"}]
    actual = [{"document_name": "leave-policy.pdf", "chunk_id": "abc"}]
    assert citation_recall(expected, actual) == 1.0


def test_score_item_blends_f1_and_recall():
    metrics = score_item(
        expected_answer="fifteen days of PTO",
        actual_answer="Employees receive fifteen days of PTO each year.",
        expected_sources=["handbook"],
        actual_sources=[{"document_name": "employee-handbook.pdf"}],
    )
    assert metrics["answer_contains_expected"] is True
    assert metrics["citation_recall"] == 1.0
    assert metrics["score"] > 0.5
