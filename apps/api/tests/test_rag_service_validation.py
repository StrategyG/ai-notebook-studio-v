from uuid import uuid4

import pytest

from ai_notebook_api.rag.service import (
    RAGService,
    _json_object,
    _vector_literal,
    validate_source_uri,
)


def test_metadata_filter_and_metadata_values_are_bounded_json_objects() -> None:
    assert _json_object({"department": "finance"}) == '{"department":"finance"}'
    with pytest.raises(ValueError, match="JSON object"):
        _json_object(["not", "an", "object"])
    with pytest.raises(ValueError, match="finite JSON"):
        _json_object({"score": float("nan")})
    with pytest.raises(ValueError, match="size limit"):
        _json_object({"payload": "x" * 20_000})


def test_source_uri_accepts_https_and_urn_but_rejects_credential_bearing_urls() -> None:
    assert validate_source_uri("https://docs.example.org/policy") == "https://docs.example.org/policy"
    assert validate_source_uri("urn:knowledge:policy:2026") == "urn:knowledge:policy:2026"
    for source in (
        "http://docs.example.org/policy",
        "https://user:password@docs.example.org/policy",
        "https://docs.example.org/policy?access_token=secret",
        "javascript:alert(1)",
    ):
        with pytest.raises(ValueError):
            validate_source_uri(source)


def test_vector_literal_requires_the_database_embedding_dimension() -> None:
    with pytest.raises(ValueError, match="dimension"):
        _vector_literal([0.1, 0.2], dimensions=1536)
    with pytest.raises(ValueError, match="non-finite"):
        _vector_literal([float("nan")] * 1536, dimensions=1536)
    with pytest.raises(ValueError, match="non-numeric"):
        _vector_literal([True] + [0.0] * 1535, dimensions=1536)


@pytest.mark.asyncio
async def test_rag_service_validates_ingestion_before_database_access() -> None:
    service = RAGService(None, tenant_id=uuid4(), actor_subject="test-actor")

    with pytest.raises(ValueError, match="title"):
        await service.ingest_document(
            title=" ",
            source_uri="urn:test:1",
            content="document text",
            metadata={},
            source_type="manual",
            embedding_model="fixture-embedding-v1",
            embedder=None,
        )
    with pytest.raises(ValueError, match="source_uri"):
        await service.ingest_document(
            title="Valid title",
            source_uri="http://invalid.example/doc",
            content="document text",
            metadata={},
            source_type="manual",
            embedding_model="fixture-embedding-v1",
            embedder=None,
        )
    with pytest.raises(ValueError, match="source_type"):
        await service.ingest_document(
            title="Valid title",
            source_uri="urn:test:1",
            content="document text",
            metadata={},
            source_type="remote-shell",
            embedding_model="fixture-embedding-v1",
            embedder=None,
        )
    with pytest.raises(ValueError, match="embedding_model"):
        await service.ingest_document(
            title="Valid title",
            source_uri="urn:test:1",
            content="document text",
            metadata={},
            source_type="manual",
            embedding_model="   ",
            embedder=None,
        )


@pytest.mark.asyncio
async def test_rag_service_rejects_invalid_search_input_before_database_access() -> None:
    service = RAGService(None, tenant_id=uuid4(), actor_subject="test-actor")

    with pytest.raises(ValueError, match="query"):
        await service.search(query=" ", embedding_model="fixture-embedding-v1", embedder=None)
    with pytest.raises(ValueError, match="limit"):
        await service.search(query="valid query", embedding_model="fixture-embedding-v1", limit=0, embedder=None)
    with pytest.raises(ValueError, match="embedding_model"):
        await service.search(query="valid query", embedding_model="   ", embedder=None)
    with pytest.raises(ValueError, match="limit"):
        await service.search(query="valid query", embedding_model="fixture-embedding-v1", limit=True, embedder=None)
    with pytest.raises(ValueError, match="JSON object"):
        await service.search(
            query="valid query",
            embedding_model="fixture-embedding-v1",
            metadata_filter=["not", "an", "object"],
            embedder=None,
        )
