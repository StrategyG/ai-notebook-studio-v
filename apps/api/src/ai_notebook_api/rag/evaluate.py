from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from statistics import mean
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from ai_notebook_api.core.config import get_settings
from ai_notebook_api.db.session import apply_tenant_database_context, get_engine
from ai_notebook_api.rag.embeddings import OpenAICompatibleEmbeddingClient
from ai_notebook_api.rag.evaluation import (
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
    unique_document_ids,
)
from ai_notebook_api.rag.service import RAGService


async def run_evaluation(dataset_path: Path) -> dict[str, object]:
    settings = get_settings()
    if not settings.persistence_configured or not settings.database_url:
        raise RuntimeError("DATABASE_URL must point to the isolated staging evaluation database")
    if not settings.rag_enabled or not settings.embedding_configured:
        raise RuntimeError("RAG_ENABLED and a real embedding provider must be configured")

    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    documents = dataset.get("documents")
    queries = dataset.get("queries")
    thresholds = dataset.get("thresholds")
    if not isinstance(documents, list) or not documents:
        raise ValueError("dataset must contain documents")
    if not isinstance(queries, list) or not queries:
        raise ValueError("dataset must contain queries")
    if not isinstance(thresholds, dict):
        raise ValueError("dataset must contain metric thresholds")

    tenant_id = uuid4()
    embedder = OpenAICompatibleEmbeddingClient(settings)
    metrics_by_query: list[dict[str, float]] = []
    engine = get_engine(settings.database_url)

    with Session(engine, expire_on_commit=False) as session:
        service = RAGService(
            session,
            tenant_id=tenant_id,
            actor_subject="rag-evaluation-runner",
        )
        try:
            document_ids: dict[str, str] = {}
            for document in documents:
                document_key = document.get("id")
                if not isinstance(document_key, str) or not document_key:
                    raise ValueError("every document needs a stable id")
                result = await service.ingest_document(
                    title=document["title"],
                    source_uri=document["source_uri"],
                    source_type=document.get("source_type", "manual"),
                    embedding_model=settings.embedding_model,
                    content=document["content"],
                    metadata=document.get("metadata", {}),
                    embedder=embedder,
                    embedding_dimensions=settings.embedding_dimensions,
                )
                document_ids[document_key] = result["document_id"]
            session.commit()

            query_results: dict[str, list[str]] = {}
            for case in queries:
                query_id = case.get("id")
                expected_keys = case.get("expected_document_ids")
                if not isinstance(query_id, str) or not isinstance(expected_keys, list) or not expected_keys:
                    raise ValueError("every query needs an id and expected_document_ids")
                missing = set(expected_keys) - set(document_ids)
                if missing:
                    raise ValueError(f"query {query_id} references unknown documents: {sorted(missing)}")
                response = await service.search(
                    query=case["query"],
                    embedding_model=settings.embedding_model,
                    embedder=embedder,
                    limit=10,
                    metadata_filter=case.get("metadata_filter", {}),
                    embedding_dimensions=settings.embedding_dimensions,
                )
                ranked = unique_document_ids(response["results"])
                query_results[query_id] = ranked
                relevant = {document_ids[key] for key in expected_keys}
                metrics_by_query.append(
                    {
                        "recall_at_5": recall_at_k(ranked, relevant, 5),
                        "mrr_at_10": mrr_at_k(ranked, relevant, 10),
                        "ndcg_at_10": ndcg_at_k(ranked, relevant, 10),
                    }
                )

            metrics = {
                metric: mean(result[metric] for result in metrics_by_query)
                for metric in ("recall_at_5", "mrr_at_10", "ndcg_at_10")
            }
            passed = {
                metric: metrics[metric] >= float(threshold)
                for metric, threshold in thresholds.items()
            }
            report: dict[str, object] = {
                "dataset_version": dataset.get("version", "unversioned"),
                "embedding_model": settings.embedding_model,
                "query_count": len(queries),
                "document_count": len(documents),
                "metrics": metrics,
                "thresholds": thresholds,
                "passed": passed,
                "release_gate_passed": bool(passed) and all(passed.values()),
            }
            return report
        finally:
            session.rollback()
            apply_tenant_database_context(session, str(tenant_id))
            session.execute(
                text("DELETE FROM rag_documents WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
            session.commit()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate RAG retrieval using a real embedding provider and PostgreSQL."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evaluation/rag_retrieval_v1.json"),
        help="Path to the versioned golden dataset (relative to apps/api by default).",
    )
    args = parser.parse_args()
    try:
        report = asyncio.run(run_evaluation(args.dataset))
    except Exception as exc:
        print(json.dumps({"release_gate_passed": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report["release_gate_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
