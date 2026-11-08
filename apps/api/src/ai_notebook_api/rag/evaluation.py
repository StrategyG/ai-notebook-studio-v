from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any


def unique_document_ids(results: Iterable[dict[str, Any]]) -> list[str]:
    """Collapse multiple retrieved chunks into their first-seen document ranking."""
    return list(dict.fromkeys(str(item["document_id"]) for item in results))


def _unique_ranked(retrieved: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(retrieved))


def _validate_k(k: int) -> None:
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be a positive integer")


def recall_at_k(retrieved: Iterable[str], relevant: set[str], k: int) -> float:
    _validate_k(k)
    if not relevant:
        return 0.0
    ranked = _unique_ranked(retrieved)
    return len(set(ranked[:k]) & relevant) / len(relevant)


def mrr_at_k(retrieved: Iterable[str], relevant: set[str], k: int) -> float:
    _validate_k(k)
    for rank, document_id in enumerate(_unique_ranked(retrieved)[:k], start=1):
        if document_id in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved: Iterable[str], relevant: set[str], k: int) -> float:
    _validate_k(k)
    if not relevant:
        return 0.0
    ranked = _unique_ranked(retrieved)[:k]
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, document_id in enumerate(ranked, start=1)
        if document_id in relevant
    )
    ideal_count = min(len(relevant), k)
    ideal_dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank in range(1, ideal_count + 1)
    )
    return dcg / ideal_dcg if ideal_dcg else 0.0
