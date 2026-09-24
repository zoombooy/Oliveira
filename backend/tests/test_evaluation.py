from app.services.evaluation import aggregate_metrics, first_relevant_rank


def test_first_relevant_rank_prefers_chunk_or_document_reference() -> None:
    retrieved = [("chunk-1", "doc-a"), ("chunk-2", "doc-b"), ("chunk-3", "doc-c")]
    assert first_relevant_rank(
        retrieved=retrieved,
        expected_chunk_ids={"chunk-2"},
        expected_document_ids=set(),
    ) == 2
    assert first_relevant_rank(
        retrieved=retrieved,
        expected_chunk_ids=set(),
        expected_document_ids={"doc-c"},
    ) == 3


def test_evaluation_metrics_calculate_hit_rate_and_mrr() -> None:
    metrics = aggregate_metrics([1, 2, None, 4], top_k=2)
    assert metrics["cases"] == 4
    assert metrics["hit_at_k"] == 0.5
    assert metrics["mrr"] == round((1 + 0.5 + 0 + 0.25) / 4, 6)


def test_empty_evaluation_is_zero_not_nan() -> None:
    assert aggregate_metrics([], top_k=8) == {
        "cases": 0,
        "hit_at_k": 0.0,
        "mrr": 0.0,
        "top_k": 8,
    }
