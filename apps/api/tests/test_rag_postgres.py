import hashlib
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from ai_notebook_api.db.session import apply_tenant_database_context
from ai_notebook_api.rag.service import RAGService

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
ADMIN_DATABASE_URL = os.getenv("TEST_ADMIN_DATABASE_URL")
DIMENSIONS = 1536


class FixedEmbeddingProvider:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        vector = [1.0] + [0.0] * (DIMENSIONS - 1)
        return [vector.copy() for _ in texts]


@pytest.mark.skipif(
    not DATABASE_URL or not ADMIN_DATABASE_URL,
    reason="PostgreSQL RAG integration databases are not configured",
)
@pytest.mark.asyncio
async def test_postgres_ingestion_hybrid_search_citations_and_tenant_isolation() -> None:
    tenant_a = uuid4()
    tenant_b = uuid4()
    admin_engine = create_engine(ADMIN_DATABASE_URL, pool_pre_ping=True)
    runtime_engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    service_content = (
        "PostgreSQL pgvector supports semantic similarity. Hybrid search combines "
        "vector similarity with PostgreSQL full text search for reliable document retrieval."
    )
    private_content = "Confidential tenant B material that must never appear in tenant A search."

    try:
        with admin_engine.begin() as connection:
            document_b = uuid4()
            connection.execute(
                text(
                    "INSERT INTO rag_documents "
                    "(id, tenant_id, title, source_uri, source_type, embedding_model, content, content_sha256, metadata, created_by) "
                    "VALUES (:id, :tenant_id, :title, :source_uri, 'manual', 'fixture-embedding-v1', :content, :content_sha256, "
                    "CAST(:metadata AS jsonb), 'integration-test')"
                ),
                {
                    "id": document_b,
                    "tenant_id": tenant_b,
                    "title": "Tenant B private source",
                    "source_uri": f"urn:rag-test:tenant-b:{tenant_b}",
                    "content": private_content,
                    "content_sha256": hashlib.sha256(private_content.encode()).hexdigest(),
                    "metadata": '{"classification":"private"}',
                },
            )
            chunk_b = uuid4()
            connection.execute(
                text(
                    "INSERT INTO rag_document_chunks "
                    "(id, tenant_id, document_id, ordinal, content, start_char, end_char, content_sha256, embedding) "
                    "VALUES (:id, :tenant_id, :document_id, 0, :content, 0, :end_char, :content_sha256, "
                    "CAST(:embedding AS vector))"
                ),
                {
                    "id": chunk_b,
                    "tenant_id": tenant_b,
                    "document_id": document_b,
                    "content": private_content,
                    "end_char": len(private_content),
                    "content_sha256": hashlib.sha256(private_content.encode()).hexdigest(),
                    "embedding": "[" + ",".join(["1"] + ["0"] * (DIMENSIONS - 1)) + "]",
                },
            )

        with Session(runtime_engine) as session:
            role = session.execute(
                text(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            ).one()
            assert role.rolsuper is False
            assert role.rolbypassrls is False
            owns_tenant_tables = session.execute(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = current_schema() "
                    "AND c.relname IN ('rag_documents', 'rag_document_chunks') "
                    "AND c.relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)"
                    ")"
                )
            ).scalar_one()
            assert owns_tenant_tables is False

            service = RAGService(session, tenant_id=tenant_a, actor_subject="rag-test-user")
            first = await service.ingest_document(
                title="PostgreSQL hybrid retrieval",
                source_uri=f"urn:rag-test:tenant-a:{tenant_a}",
                source_type="manual",
                embedding_model="fixture-embedding-v1",
                content=service_content,
                metadata={"classification": "internal", "topic": "database"},
                embedder=FixedEmbeddingProvider(),
            )
            second_tenant_a = await service.ingest_document(
                title="Tenant A security policy",
                source_uri=f"urn:rag-test:tenant-a-security:{tenant_a}",
                source_type="manual",
                content="Tenant A security policy describes access control and identity protection.",
                metadata={"classification": "internal", "topic": "security"},
                embedding_model="fixture-embedding-v1",
                embedder=FixedEmbeddingProvider(),
            )
            session.commit()

            repeated = await service.ingest_document(
                title="PostgreSQL hybrid retrieval",
                source_uri=f"urn:rag-test:tenant-a:{tenant_a}",
                source_type="manual",
                embedding_model="fixture-embedding-v1",
                content=service_content,
                metadata={"classification": "internal", "topic": "database"},
                embedder=FixedEmbeddingProvider(),
            )
            assert repeated["reused"] is True
            assert repeated["document_id"] == first["document_id"]
            assert repeated["chunk_count"] == first["chunk_count"]

            response = await service.search(
                query="pgvector hybrid search",
                embedding_model="fixture-embedding-v1",
                limit=5,
                metadata_filter={"topic": "database"},
                embedder=FixedEmbeddingProvider(),
            )
            assert response["results"]
            assert {item["document_id"] for item in response["results"]} == {
                first["document_id"]
            }
            filtered_security = await service.search(
                query="security policy access control",
                embedding_model="fixture-embedding-v1",
                limit=5,
                metadata_filter={"topic": "security"},
                embedder=FixedEmbeddingProvider(),
            )
            assert {item["document_id"] for item in filtered_security["results"]} == {
                second_tenant_a["document_id"]
            }
            assert service.get_document(document_b) is None
            assert service.get_chunk_source(document_b, chunk_b) is None
            citation = response["citations"][0]
            assert citation["source_sha256"] == first["content_sha256"]

            source = service.get_chunk_source(
                UUID(citation["document_id"]),
                UUID(citation["chunk_id"]),
            )
            assert source is not None
            assert source["source_hash_valid"] is True
            assert source["chunk_hash_valid"] is True
            assert source["offsets_valid"] is True

            document = service.get_document(UUID(first["document_id"]))
            assert document is not None
            assert document["content_hash_valid"] is True
            assert document["content"] == service_content

            # Explicit cross-tenant reads remain invisible with tenant A context.
            cross_tenant_rows = session.execute(
                text("SELECT id FROM rag_documents WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_b},
            ).all()
            assert cross_tenant_rows == []
            assert service.get_document(document_b) is None

            updated = session.execute(
                text(
                    "UPDATE rag_documents SET title = 'tampered' "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_b},
            )
            deleted = session.execute(
                text("DELETE FROM rag_documents WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_b},
            )
            assert updated.rowcount == 0
            assert deleted.rowcount == 0

        # A runtime role cannot insert into another tenant by supplying its ID.
        with Session(runtime_engine) as session:
            apply_tenant_database_context(session, str(tenant_a))
            with pytest.raises(DBAPIError):
                session.execute(
                    text(
                        "INSERT INTO rag_documents "
                        "(id, tenant_id, title, source_uri, source_type, embedding_model, content, "
                        "content_sha256, metadata, created_by) "
                        "VALUES (:id, :tenant_id, 'forbidden', :source_uri, 'manual', "
                        "'fixture-embedding-v1', :content, :content_sha256, '{}'::jsonb, 'attacker')"
                    ),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_b,
                        "source_uri": f"urn:rag-test:forbidden:{tenant_b}",
                        "content": "cross tenant write must fail",
                        "content_sha256": hashlib.sha256(b"cross tenant write must fail").hexdigest(),
                    },
                )
                session.commit()
            session.rollback()

        # Missing tenant context is also fail-closed.
        with Session(runtime_engine) as session:
            visible = session.execute(
                text("SELECT id FROM rag_documents WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_b},
            ).all()
            assert visible == []
    finally:
        with admin_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM rag_documents WHERE tenant_id IN (:tenant_a, :tenant_b)"),
                {"tenant_a": tenant_a, "tenant_b": tenant_b},
            )
        runtime_engine.dispose()
        admin_engine.dispose()
