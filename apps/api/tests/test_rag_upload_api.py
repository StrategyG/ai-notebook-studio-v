from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ai_notebook_api.api import rag_upload as upload_api
from ai_notebook_api.core.config import Settings, get_settings
from ai_notebook_api.db.base import Base
from ai_notebook_api.db.models import TenantMembership
from ai_notebook_api.db.session import get_tenant_session
from ai_notebook_api.main import app
from ai_notebook_api.security.auth import Principal, get_current_principal

TENANT_ID = UUID("d2719d9a-3b0a-4b8a-a95b-1a8a1efc7f8e")
ISSUER = "https://identity.example/"


class FakeUploadRAGService:
    calls: list[dict] = []

    def __init__(self, _session: Session, *, tenant_id: UUID, actor_subject: str):
        assert tenant_id == TENANT_ID
        assert actor_subject == "upload-user"

    async def ingest_document(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "document_id": "d9d50c4a-5c50-4bb6-bfa0-7e9d00c33c12",
            "content_sha256": "a" * 64,
            "chunk_count": 1,
            "indexed": True,
            "reused": False,
        }


@pytest.fixture
def upload_client(monkeypatch) -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    session.add(
        TenantMembership(
            tenant_id=TENANT_ID,
            issuer=ISSUER,
            subject="upload-user",
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
        subject="upload-user",
        tenant_id=TENANT_ID,
        roles=frozenset({"viewer"}),
        scopes=frozenset({"documents:write"}),
    )

    def override_session():
        yield session

    FakeUploadRAGService.calls = []
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_tenant_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(upload_api, "RAGService", FakeUploadRAGService)
    monkeypatch.setattr(upload_api, "OpenAICompatibleEmbeddingClient", lambda _settings: object())

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    session.close()
    engine.dispose()


def test_upload_route_indexes_utf8_text_with_file_provenance(upload_client: TestClient) -> None:
    response = upload_client.post(
        "/api/v1/rag/documents/upload",
        files={"file": ("tenant-policy.txt", b"Tenant A data must remain private.", "text/plain")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["indexed"] is True
    assert payload["parser"] == "utf-8-text"
    assert payload["file_sha256"]
    assert FakeUploadRAGService.calls[0]["source_type"] == "upload"
    assert FakeUploadRAGService.calls[0]["content"] == "Tenant A data must remain private."
    assert FakeUploadRAGService.calls[0]["metadata"]["original_filename"] == "tenant-policy.txt"
    assert FakeUploadRAGService.calls[0]["metadata"]["parser"] == "utf-8-text"


def test_upload_route_rejects_unsupported_file_types(upload_client: TestClient) -> None:
    response = upload_client.post(
        "/api/v1/rag/documents/upload",
        files={"file": ("payload.exe", b"not an executable parser input", "application/octet-stream")},
    )

    assert response.status_code == 422
    assert "Supported upload types" in response.json()["detail"]


def test_upload_route_rejects_oversized_file_before_parsing(
    upload_client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(upload_api, "MAX_UPLOAD_BYTES", 8)
    response = upload_client.post(
        "/api/v1/rag/documents/upload",
        files={"file": ("large.txt", b"x" * 9, "text/plain")},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "document_upload_too_large"
