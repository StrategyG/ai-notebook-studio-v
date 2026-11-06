from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from statistics import mean
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from ai_notebook_api.core.config import get_settings, validate_rag_configuration
from ai_notebook_api.db.session import get_engine
from ai_notebook_api.rag.chunking import chunk_text
from ai_notebook_api.rag.embeddings import OpenAICompatibleEmbeddingClient
from ai_notebook_api.rag.evaluation import (
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
    unique_document_ids,
)
from ai_notebook_api.rag.service import RAGService

DATASET_PATH = Path(__file__).resolve().parents[1] / "tests" / "evaluation" / "rag_retrieval.json"


class PrecomputedEmbeddingProvider:
    """Supply vectors obtained from the configured remote provider before DB work begins."""

    def __init__(self, vectors: list[list[float]]):
        self.vectors = vectors

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if len(texts) != len(self.vectors):
            raise ValueError("precomputed evaluation vectors do not match the requested batch")
        return self.vectors


def _assert_restricted_runtime_role(session: Session) -> None:
    role = session.execute(
        text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).one_or_none()
    if role is None or bool(role.rolsuper) or bool(role.rolbypassrls):
        raise RuntimeError("retrieval evaluation requires a non-superuser NOBYPASSRLS database role")

    owns_tenant_tables = session.execute(
        text(
            "SELECT EXISTS ("
            "SELECT 1 FROM pg_class "
            "WHERE oid IN (to_regclass('rag_documents'), to_regclass('rag_document_chunks')) "
            "AND relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)"
            ")"
        )
    ).scalar_one()
    if owns_tenant_tables:
        raise RuntimeError("retrieval evaluation role must not own tenant RAG tables")

    rls = session.execute(
        text(
            "SELECT count(*) FROM pg_class "
            "WHERE oid IN (to_regclass('rag_documents'), to_regclass('rag_document_chunks')) "
            "AND relrowsecurity AND relforcerowsecurity"
        )
    ).scalar_one()
    if int(rls) != 2:
        raise RuntimeError("forced row-level security is required on both RAG tables")


def _citation_is_verifiable(service: RAGService, citation: dict[str, object]) -> bool:
    try:
        source = service.get_chunk_source(
            UUID(str(citation["document_id"])),
            UUID(str(citation["chunk_id"])),
        )
    except (KeyError, ValueError, TypeError):
        return False
    return bool(
        source
        and source["source_uri"] == citation.get("source_uri")
        and source["source_sha256"] == citation.get("source_sha256")
        and source["chunk_sha256"] == citation.get("chunk_sha256")
        and source["source_hash_valid"]
        and source["chunk_hash_valid"]
        and source["offsets_valid"]
    )


async def evaluate() -> int:
    settings = get_settings()
    validate_rag_configuration(settings)
    if not settings.rag_enabled or not settings.persistence_configured or not settings.database_url:
        raise RuntimeError("RAG_ENABLED and DATABASE_URL are required for retrieval evaluation")

    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    if not dataset.get("documents") or not dataset.get("queries") or not dataset.get("targets"):
        raise RuntimeError("retrieval evaluation dataset is incomplete")

    embedder = OpenAICompatibleEmbeddingClient(settings)

    # Obtain every real vector before opening a database transaction. This prevents
    # remote embedding latency from holding a pooled PostgreSQL connection or snapshot.
    document_vectors: dict[str, list[list[float]]] = {}
    for document in dataset["documents"]:
        chunks = chunk_text(document["content"])
        document_vectors[document["id"]] = await embedder.embed([chunk.text for chunk in chunks])

    query_vectors: dict[str, list[float]] = {}
    for query in dataset["queries"]:
        vectors = await embedder.embed([query["query"]])
        if len(vectors) != 1:
            raise RuntimeError("embedding provider returned an invalid query vector count")
        query_vectors[query["id"]] = vectors[0]

    engine = get_engine(settings.database_url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session: Session = factory()
    tenant_id = uuid4()
    try:
        _assert_restricted_runtime_role(session)
        session.commit()
        service = RAGService(session, tenant_id=tenant_id, actor_subject="rag-evaluation")

        indexed: dict[str, str] = {}
        for document in dataset["documents"]:
            result = await service.ingest_document(
                title=document["title"],
                source_uri=document["source_uri"],
                source_type="manual",
                content=document["content"],
                metadata=document["metadata"],
                embedding_model=settings.embedding_model,
                embedder=PrecomputedEmbeddingProvider(document_vectors[document["id"]]),
                embedding_dimensions=settings.embedding_dimensions,
            )
            indexed[document["id"]] = result["document_id"]

        metric_rows: list[dict[str, float | str]] = []
        citation_count = 0
        verified_citation_count = 0
        for query in dataset["queries"]:
            relevant = {indexed[item] for item in query["relevant_document_ids"]}
            response = await service.search(
                query=query["query"],
                metadata_filter=query.get("metadata_filter", {}),
                embedding_model=settings.embedding_model,
                limit=10,
                embedder=PrecomputedEmbeddingProvider([query_vectors[query["id"]]]),
                embedding_dimensions=settings.embedding_dimensions,
            )
            retrieved = unique_document_ids(response["results"])
            citations = response["citations"]
            citation_count += len(citations)
            verified_for_query = sum(
                1 for citation in citations if _citation_is_verifiable(service, citation)
            )
            verified_citation_count += verified_for_query
            citation_integrity = (
                verified_for_query / len(citations) if citations else 0.0
            )
            metric_rows.append(
                {
                    "query_id": query["id"],
                    "recall_at_5": recall_at_k(retrieved, relevant, 5),
                    "mrr_at_10": mrr_at_k(retrieved, relevant, 10),
                    "ndcg_at_10": ndcg_at_k(retrieved, relevant, 10),
                    "citation_integrity_rate": citation_integrity,
                }
            )

        measured = {
            metric: mean(float(row[metric]) for row in metric_rows)
            for metric in (
                "recall_at_5",
                "mrr_at_10",
                "ndcg_at_10",
                "citation_integrity_rate",
            )
        }
        targets = dataset["targets"]
        if any(name not in measured for name in targets):
            raise RuntimeError("evaluation dataset contains an unsupported metric target")
        passed = all(measured[name] >= targets[name] for name in targets)
        report = {
            "dataset_version": dataset["dataset_version"],
            "embedding_model": settings.embedding_model,
            "tenant_id": str(tenant_id),
            "query_count": len(metric_rows),
            "citation_count": citation_count,
            "verified_citation_count": verified_citation_count,
            "targets": targets,
            "measured": measured,
            "per_query": metric_rows,
            "passed": passed,
            "database_role_rls_verified": True,
            "fixture_writes_rolled_back": True,
        }
        print(json.dumps(report, indent=2))
        return 0 if passed else 1
    finally:
        session.rollback()
        session.close()
        engine.dispose()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(evaluate()))
    except Exception as exc:
        print(f"RAG evaluation failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(2) from exc
