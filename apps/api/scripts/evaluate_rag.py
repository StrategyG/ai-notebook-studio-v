from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from ai_notebook_api.core.config import get_settings, validate_rag_configuration
from ai_notebook_api.db.session import get_engine, apply_tenant_database_context
from ai_notebook_api.rag.embeddings import OpenAICompatibleEmbeddingClient
from ai_notebook_api.rag.service import RAGService

DATASET_PATH = Path(__file__).resolve().parents[1] / "tests" / "evaluation" / "rag_retrieval.json"


def _unique_document_ids(results: list[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(item["document_id"] for item in results))


def _recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(retrieved[:k]) & relevant) / len(relevant)


def _mrr_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    for rank, document_id in enumerate(retrieved[:k], start=1):
        if document_id in relevant:
            return 1.0 / rank
    return 0.0


def _ndcg_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    dcg = sum(
        1.0 / __import__("math").log2(rank + 1)
        for rank, document_id in enumerate(retrieved[:k], start=1)
        if document_id in relevant
    )
    ideal_count = min(len(relevant), k)
    ideal_dcg = sum(
        1.0 / __import__("math").log2(rank + 1)
        for rank in range(1, ideal_count + 1)
    )
    return dcg / ideal_dcg if ideal_dcg else 0.0


async def evaluate() -> int:
    settings = get_settings()
    validate_rag_configuration(settings)
    if not settings.rag_enabled or not settings.persistence_configured or not settings.database_url:
        raise RuntimeError("RAG_ENABLED and DATABASE_URL are required for retrieval evaluation")
    tenant_value = os.getenv("RAG_EVAL_TENANT_ID")
    if not tenant_value:
        raise RuntimeError("RAG_EVAL_TENANT_ID must be a fresh, isolated evaluation tenant UUID")
    tenant_id = UUID(tenant_value)

    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    engine = get_engine(settings.database_url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session: Session = factory()
    embedder = OpenAICompatibleEmbeddingClient(settings)
    try:
        service = RAGService(session, tenant_id=tenant_id, actor_subject="rag-evaluation")
        apply_tenant_database_context(session, str(tenant_id))

        indexed: dict[str, str] = {}
        for document in dataset["documents"]:
            result = await service.ingest_document(
                title=document["title"],
                source_uri=document["source_uri"],
                source_type="manual",
                content=document["content"],
                metadata=document["metadata"],
                embedder=embedder,
                embedding_dimensions=settings.embedding_dimensions,
            )
            indexed[document["id"]] = result["document_id"]
        session.commit()

        metric_rows: list[dict[str, float | str]] = []
        for query in dataset["queries"]:
            relevant = {indexed[item] for item in query["relevant_document_ids"]}
            response = await service.search(
                query=query["query"],
                limit=10,
                embedder=embedder,
                embedding_dimensions=settings.embedding_dimensions,
            )
            retrieved = _unique_document_ids(response["results"])
            metric_rows.append(
                {
                    "query_id": query["id"],
                    "recall_at_5": _recall_at_k(retrieved, relevant, 5),
                    "mrr_at_10": _mrr_at_k(retrieved, relevant, 10),
                    "ndcg_at_10": _ndcg_at_k(retrieved, relevant, 10),
                }
            )

        measured = {
            metric: mean(float(row[metric]) for row in metric_rows)
            for metric in ("recall_at_5", "mrr_at_10", "ndcg_at_10")
        }
        targets = dataset["targets"]
        passed = all(measured[name] >= targets[name] for name in targets)
        report = {
            "dataset_version": dataset["dataset_version"],
            "tenant_id": str(tenant_id),
            "query_count": len(metric_rows),
            "targets": targets,
            "measured": measured,
            "per_query": metric_rows,
            "passed": passed,
        }
        print(json.dumps(report, indent=2))
        return 0 if passed else 1
    finally:
        session.close()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(evaluate()))
    except Exception as exc:
        print(f"RAG evaluation failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(2) from exc
