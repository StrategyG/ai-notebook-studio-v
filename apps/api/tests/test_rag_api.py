from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ai_notebook_api.api import rag as rag_api
from ai_notebook_api.core.config import Settings, get_settings
from ai_notebook_api.db.base import Base
from ai_notebook_api.db.models import TenantMembership
from ai_notebook_api.db.session import get_tenant_session
from ai_notebook_api.main import app
from ai_notebook_api.security.auth import Principal, get_current_principal

TENANT_ID = UUID("d2719d9a-3b0a-4b8a-a95b-1a8a1efc7f8e")
ISSUER = "https://identity.example/"
DOCUMENT_ID = "d9d50c4a-5c50-4bb6-bfa0-7e9d00c33c12"
CHUNK_ID = "b5cdb65d-b43b-46de-9d86-47c915c66f1a"


class FakeRAGService:
    def __init__(self, _session: Session, *, tenant_id: UUID, actor_subject: str):
        assert tenant_id == TENANT_ID
        assert actor_subject == "api-user"

    async def ingest_document(self, **kwargs):
        assert kwargs["embedding_model"] == "test-embedding-model"
        return {
            "document_id": DOCUMENT_ID,
            "content_sha256": "a" * 64,
            "chunk_count": 2,
            "indexed": True,
            "reused": False,
        }

    async def search(self, **kwargs):
        assert kwargs["query"] == "tenant isolation"
        return {
            "query": kwargs["query"],
            "results": [],
            "citations": [],
        }

    def get_document(self, document_id: UUID):
        if str(document_id) != DOCUMENT_ID:
            return None
        return {
            "document_id": DOCUMENT_ID,
            "title": "Tenant policy",
            "content_hash_valid": True,
        }

    def get_chunk_source(self, document_id: UUID, chunk_id: UUID):
        if str(document_id) != DOCUMENT_ID or str(chunk_id) != CHUNK_ID:
            return None
        return {
            "document_id": DOCUMENT_ID,
            "chunk_id": CHUNK_ID,
            "source_hash_valid": True,
            "chunk_hash_valid": True,
            "offsets_valid": True,
        }


@pytest.fixture
def api_client(monkeypatch) -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(
        TenantMembership(
            tenant_id=TENANT_ID,
            issuer=ISSUER,
            subject="api-user",
            role="owner",
            status="active",
        )
    )
    session.commit()

    settings = Settings(
        rag_enabled=True,
        embedding_api_url="https://embedding.example/v1/embeddings",
        embedding_api_key="test-secret",
        embedding_model="test-embedding-model",
        embedding_dimensions=1536,
    )
    principal = Principal(
        issuer=ISSUER,
        subject="api-user",
        tenant_id=TENANT_ID,
        roles=frozenset({"viewer"}),
        scopes=frozenset({"documents:read", "documents:write", "rag:search"}),
    )

    def override_session():
        yield session

    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_tenant_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(rag_api, "RAGService", FakeRAGService)
    monkeypatch.setattr(rag_api, "OpenAICompatibleEmbeddingClient", lambda _settings: object())

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    session.close()
    engine.dispose()


def test_document_ingestion_route_returns_index_receipt(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/v1/rag/documents",
        json={
            "title": "Tenant policy",
            "source_uri": "urn:tenant:policy:v1",
            "source_type": "manual",
            "content": "A tenant scoped source document.",
            "metadata": {"department": "engineering"},
        },
    )

    assert response.status_code == 201
    assert response.json()["indexed"] is True
    assert response.json()["chunk_count"] == 2


def test_search_route_returns_citations_container(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/v1/rag/search",
        json={"query": "tenant isolation", "limit": 5, "metadata_filter": {"area": "security"}},
    )

    assert response.status_code == 200
    assert response.json() == {"query": "tenant isolation", "results": [], "citations": []}


def test_document_and_citation_source_routes_are_tenant_scoped(api_client: TestClient) -> None:
    document = api_client.get(f"/api/v1/rag/documents/{DOCUMENT_ID}")
    citation = api_client.get(
        f"/api/v1/rag/documents/{DOCUMENT_ID}/chunks/{CHUNK_ID}"
    )

    assert document.status_code == 200
    assert document.json()["content_hash_valid"] is True
    assert citation.status_code == 200
    assert citation.json()["offsets_valid"] is True


def test_document_and_citation_routes_return_not_found_for_unknown_ids(api_client: TestClient) -> None:
    document = api_client.get(f"/api/v1/rag/documents/{uuid4()}")
    citation = api_client.get(
        f"/api/v1/rag/documents/{DOCUMENT_ID}/chunks/{uuid4()}"
    )

    assert document.status_code == 404
    assert citation.status_code == 404


def test_rag_routes_fail_closed_when_embedding_service_is_disabled(api_client: TestClient) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(rag_enabled=False)
    response = api_client.post("/api/v1/rag/search", json={"query": "tenant isolation"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rag_embedding_service_unavailable"
