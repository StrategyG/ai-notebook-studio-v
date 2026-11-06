import pytest

from ai_notebook_api.rag.evaluation import (
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
    unique_document_ids,
)


def test_unique_document_ids_keeps_first_chunk_rank_for_each_document() -> None:
    results = [
        {"document_id": "doc-a"},
        {"document_id": "doc-a"},
        {"document_id": "doc-b"},
        {"document_id": "doc-c"},
        {"document_id": "doc-b"},
    ]

    assert unique_document_ids(results) == ["doc-a", "doc-b", "doc-c"]


def test_recall_at_k_uses_unique_documents_and_all_relevant_sources() -> None:
    assert recall_at_k(["a", "a", "b", "c"], {"a", "b", "d"}, 3) == pytest.approx(2 / 3)


def test_mrr_at_k_rewards_first_relevant_document() -> None:
    assert mrr_at_k(["noise", "noise", "relevant", "other"], {"relevant"}, 3) == pytest.approx(1 / 2)


def test_ndcg_at_k_uses_binary_relevance_and_ideal_ranking() -> None:
    assert ndcg_at_k(["noise", "relevant-a", "relevant-b"], {"relevant-a", "relevant-b"}, 3) == pytest.approx(
        (1 / 2 + 1 / 1.584962500721156) / (1 + 1 / 1.584962500721156)
    )


def test_metrics_return_zero_for_empty_relevant_set() -> None:
    assert recall_at_k(["a"], set(), 5) == 0.0
    assert mrr_at_k(["a"], set(), 5) == 0.0
    assert ndcg_at_k(["a"], set(), 5) == 0.0


@pytest.mark.parametrize("k", [0, -1, True, 1.5])
def test_metrics_reject_invalid_k(k) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        recall_at_k(["a"], {"a"}, k)
