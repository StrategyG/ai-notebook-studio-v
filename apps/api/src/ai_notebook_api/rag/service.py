from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from ai_notebook_api.db.session import apply_tenant_database_context
from ai_notebook_api.rag.chunking import chunk_text
from ai_notebook_api.rag.embeddings import EmbeddingProvider


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _vector_literal(vector: list[float], *, dimensions: int) -> str:
    if len(vector) != dimensions:
        raise ValueError("embedding dimension does not match the database schema")
    return "[" + ",".join(format(float(value), ".9g") for value in vector) + "]"


def _json_object(value: dict[str, Any] | None, *, maximum_bytes: int = 16_384) -> str:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("metadata must be a JSON object")
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata must contain finite JSON values") from exc
    if len(encoded.encode("utf-8")) > maximum_bytes:
        raise ValueError("metadata exceeds the size limit")
    return encoded


def validate_source_uri(source_uri: str) -> str:
    if not isinstance(source_uri, str) or not source_uri or len(source_uri) > 2048:
        raise ValueError("source_uri must contain between 1 and 2048 characters")
    if any(character.isspace() for character in source_uri):
        raise ValueError("source_uri must not contain whitespace")
    parsed = urlsplit(source_uri)
    if parsed.scheme == "urn":
        if not (parsed.path or parsed.netloc):
            raise ValueError("URN source_uri is invalid")
        return source_uri
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("source_uri must be an HTTPS URL without credentials, query, or fragment, or a URN")
    return source_uri


class RAGService:
    """PostgreSQL-backed document ingestion and hybrid retrieval for one verified tenant."""

    def __init__(self, session: Session, *, tenant_id: UUID, actor_subject: str):
        if not actor_subject or len(actor_subject) > 255:
            raise ValueError("actor identity is invalid")
        self.session = session
        self.tenant_id = tenant_id
        self.actor_subject = actor_subject

    async def ingest_document(
        self,
        *,
        title: str,
        source_uri: str,
        content: str,
        metadata: dict[str, Any] | None,
        source_type: str,
        embedding_model: str,
        embedder: EmbeddingProvider,
        embedding_dimensions: int = 1536,
    ) -> dict[str, Any]:
        if not title or not title.strip() or len(title) > 512:
            raise ValueError("title must contain between 1 and 512 characters")
        if not isinstance(content, str) or not content.strip() or len(content) > 1_000_000:
            raise ValueError("content must contain between 1 and 1000000 non-whitespace characters")
        if source_type not in {"url", "upload", "manual", "repository"}:
            raise ValueError("source_type is not supported")
        if not embedding_model or len(embedding_model) > 128:
            raise ValueError("embedding_model must contain between 1 and 128 characters")
        source_uri = validate_source_uri(source_uri)
        metadata_json = _json_object(metadata)
        apply_tenant_database_context(self.session, str(self.tenant_id))

        source_hash = _sha256(content)
        existing = self.session.execute(
            text(
                "SELECT id, (SELECT count(*) FROM rag_document_chunks c "
                "WHERE c.document_id = d.id AND c.tenant_id = d.tenant_id) AS chunk_count "
                "FROM rag_documents d "
                "WHERE d.tenant_id = :tenant_id AND d.source_uri = :source_uri "
                "AND d.content_sha256 = :source_hash AND d.embedding_model = :embedding_model"
            ),
            {
                "tenant_id": self.tenant_id,
                "source_uri": source_uri,
                "source_hash": source_hash,
                "embedding_model": embedding_model,
            },
        ).mappings().first()
        if existing is not None:
            return {
                "document_id": str(existing["id"]),
                "content_sha256": source_hash,
                "chunk_count": int(existing["chunk_count"]),
                "indexed": True,
                "reused": True,
            }

        chunks = chunk_text(content)
        vectors = await embedder.embed([chunk.text for chunk in chunks])
        if len(vectors) != len(chunks):
            raise ValueError("embedding provider did not return one vector per chunk")

        document_id = uuid4()
        self.session.execute(
            text(
                "INSERT INTO rag_documents "
                "(id, tenant_id, title, source_uri, source_type, embedding_model, content, content_sha256, metadata, created_by) "
                "VALUES (:id, :tenant_id, :title, :source_uri, :source_type, :embedding_model, :content, :content_sha256, "
                "CAST(:metadata AS jsonb), :created_by)"
            ),
            {
                "id": document_id,
                "tenant_id": self.tenant_id,
                "title": title.strip(),
                "source_uri": source_uri,
                "source_type": source_type,
                "embedding_model": embedding_model,
                "content": content,
                "content_sha256": source_hash,
                "metadata": metadata_json,
                "created_by": self.actor_subject,
            },
        )

        for chunk, vector in zip(chunks, vectors, strict=True):
            self.session.execute(
                text(
                    "INSERT INTO rag_document_chunks "
                    "(id, tenant_id, document_id, ordinal, content, start_char, end_char, content_sha256, embedding) "
                    "VALUES (:id, :tenant_id, :document_id, :ordinal, :content, :start_char, :end_char, "
                    ":content_sha256, CAST(:embedding AS vector))"
                ),
                {
                    "id": uuid4(),
                    "tenant_id": self.tenant_id,
                    "document_id": document_id,
                    "ordinal": chunk.ordinal,
                    "content": chunk.text,
                    "start_char": chunk.start_char,
                    "end_char": chunk.end_char,
                    "content_sha256": _sha256(chunk.text),
                    "embedding": _vector_literal(vector, dimensions=embedding_dimensions),
                },
            )

        return {
            "document_id": str(document_id),
            "content_sha256": source_hash,
            "chunk_count": len(chunks),
            "indexed": True,
            "reused": False,
        }

    async def search(
        self,
        *,
        query: str,
        embedder: EmbeddingProvider,
        embedding_model: str,
        limit: int = 5,
        metadata_filter: dict[str, Any] | None = None,
        embedding_dimensions: int = 1536,
    ) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip() or len(query) > 2000:
            raise ValueError("query must contain between 1 and 2000 characters")
        if not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")
        if not embedding_model or len(embedding_model) > 128:
            raise ValueError("embedding_model must contain between 1 and 128 characters")
        metadata_json = _json_object(metadata_filter, maximum_bytes=4096)
        apply_tenant_database_context(self.session, str(self.tenant_id))

        vectors = await embedder.embed([query.strip()])
        if len(vectors) != 1:
            raise ValueError("embedding provider did not return one query vector")
        embedding = _vector_literal(vectors[0], dimensions=embedding_dimensions)
        candidate_limit = min(max(limit * 4, 20), 100)

        statement = text(
            """
            WITH vector_candidates AS (
                SELECT c.id,
                       row_number() OVER (
                           ORDER BY c.embedding <=> CAST(:embedding AS vector), c.id
                       ) AS vector_rank
                FROM rag_document_chunks c
                JOIN rag_documents d
                  ON d.id = c.document_id AND d.tenant_id = c.tenant_id
                WHERE c.tenant_id = :tenant_id
                  AND d.tenant_id = :tenant_id
                  AND d.embedding_model = :embedding_model
                  AND d.metadata @> CAST(:metadata_filter AS jsonb)
                ORDER BY c.embedding <=> CAST(:embedding AS vector), c.id
                LIMIT :candidate_limit
            ),
            lexical_candidates AS (
                SELECT c.id,
                       row_number() OVER (
                           ORDER BY ts_rank_cd(
                               c.search_tsv, websearch_to_tsquery('simple', :query)
                           ) DESC, c.id
                       ) AS lexical_rank
                FROM rag_document_chunks c
                JOIN rag_documents d
                  ON d.id = c.document_id AND d.tenant_id = c.tenant_id
                WHERE c.tenant_id = :tenant_id
                  AND d.tenant_id = :tenant_id
                  AND d.metadata @> CAST(:metadata_filter AS jsonb)
                  AND c.search_tsv @@ websearch_to_tsquery('simple', :query)
                ORDER BY ts_rank_cd(
                    c.search_tsv, websearch_to_tsquery('simple', :query)
                ) DESC, c.id
                LIMIT :candidate_limit
            ),
            ranked AS (
                SELECT id, 1.0 / (60 + vector_rank) AS reciprocal_rank
                FROM vector_candidates
                UNION ALL
                SELECT id, 1.0 / (60 + lexical_rank) AS reciprocal_rank
                FROM lexical_candidates
            ),
            fused AS (
                SELECT id, sum(reciprocal_rank) AS hybrid_score
                FROM ranked
                GROUP BY id
            )
            SELECT c.id AS chunk_id,
                   c.document_id,
                   c.ordinal,
                   c.content,
                   c.start_char,
                   c.end_char,
                   c.content_sha256 AS chunk_sha256,
                   d.title,
                   d.source_uri,
                   d.content_sha256 AS source_sha256,
                   d.embedding_model,
                   d.metadata,
                   fused.hybrid_score
            FROM fused
            JOIN rag_document_chunks c ON c.id = fused.id
            JOIN rag_documents d
              ON d.id = c.document_id AND d.tenant_id = c.tenant_id
            WHERE c.tenant_id = :tenant_id AND d.tenant_id = :tenant_id
            ORDER BY fused.hybrid_score DESC, c.id
            LIMIT :limit
            """
        )
        rows = self.session.execute(
            statement,
            {
                "embedding": embedding,
                "tenant_id": self.tenant_id,
                "embedding_model": embedding_model,
                "metadata_filter": metadata_json,
                "query": query.strip(),
                "candidate_limit": candidate_limit,
                "limit": limit,
            },
        ).mappings().all()

        results: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        for row in rows:
            citation = {
                "citation_id": f"{row['document_id']}:{row['chunk_id']}",
                "document_id": str(row["document_id"]),
                "chunk_id": str(row["chunk_id"]),
                "title": row["title"],
                "source_uri": row["source_uri"],
                "source_sha256": row["source_sha256"],
                "embedding_model": row["embedding_model"],
                "chunk_sha256": row["chunk_sha256"],
                "start_char": int(row["start_char"]),
                "end_char": int(row["end_char"]),
                "excerpt": row["content"],
            }
            citations.append(citation)
            results.append(
                {
                    "chunk_id": str(row["chunk_id"]),
                    "document_id": str(row["document_id"]),
                    "text": row["content"],
                    "score": float(row["hybrid_score"]),
                    "metadata": row["metadata"],
                    "citation": citation,
                }
            )
        return {"query": query.strip(), "results": results, "citations": citations}

    def get_document(self, document_id: UUID) -> dict[str, Any] | None:
        apply_tenant_database_context(self.session, str(self.tenant_id))
        row = self.session.execute(
            text(
                "SELECT id, title, source_uri, source_type, embedding_model, content, content_sha256, metadata, created_at "
                "FROM rag_documents WHERE id = :document_id AND tenant_id = :tenant_id"
            ),
            {"document_id": document_id, "tenant_id": self.tenant_id},
        ).mappings().first()
        if row is None:
            return None
        content = row["content"]
        actual_hash = _sha256(content)
        return {
            "document_id": str(row["id"]),
            "title": row["title"],
            "source_uri": row["source_uri"],
            "source_type": row["source_type"],
            "embedding_model": row["embedding_model"],
            "content": content,
            "content_sha256": row["content_sha256"],
            "content_hash_valid": actual_hash == row["content_sha256"],
            "metadata": row["metadata"],
            "created_at": row["created_at"].isoformat(),
        }

    def get_chunk_source(self, document_id: UUID, chunk_id: UUID) -> dict[str, Any] | None:
        apply_tenant_database_context(self.session, str(self.tenant_id))
        row = self.session.execute(
            text(
                "SELECT d.title, d.source_uri, d.content AS source_content, "
                "d.content_sha256 AS source_sha256, c.id AS chunk_id, c.content AS chunk_content, "
                "c.content_sha256 AS chunk_sha256, c.start_char, c.end_char "
                "FROM rag_documents d JOIN rag_document_chunks c "
                "ON c.document_id = d.id AND c.tenant_id = d.tenant_id "
                "WHERE d.id = :document_id AND c.id = :chunk_id AND d.tenant_id = :tenant_id"
            ),
            {
                "document_id": document_id,
                "chunk_id": chunk_id,
                "tenant_id": self.tenant_id,
            },
        ).mappings().first()
        if row is None:
            return None

        source_content = row["source_content"]
        start_char = int(row["start_char"])
        end_char = int(row["end_char"])
        excerpt = row["chunk_content"]
        return {
            "document_id": str(document_id),
            "chunk_id": str(row["chunk_id"]),
            "title": row["title"],
            "source_uri": row["source_uri"],
            "source_sha256": row["source_sha256"],
            "chunk_sha256": row["chunk_sha256"],
            "start_char": start_char,
            "end_char": end_char,
            "excerpt": excerpt,
            "source_hash_valid": _sha256(source_content) == row["source_sha256"],
            "chunk_hash_valid": _sha256(excerpt) == row["chunk_sha256"],
            "offsets_valid": source_content[start_char:end_char] == excerpt,
        }
