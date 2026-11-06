from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ai_notebook_api.core.config import Settings, get_settings
from ai_notebook_api.db.models import TenantMembership
from ai_notebook_api.db.session import get_tenant_session
from ai_notebook_api.rag.embeddings import EmbeddingServiceError, OpenAICompatibleEmbeddingClient
from ai_notebook_api.rag.service import RAGService
from ai_notebook_api.security.tenant import require_tenant_permissions

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])

require_documents_read = require_tenant_permissions("documents:read")
require_documents_write = require_tenant_permissions("documents:write")
require_rag_search = require_tenant_permissions("rag:search")


class DocumentIngestRequest(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    source_uri: str = Field(min_length=1, max_length=2048)
    source_type: Literal["url", "upload", "manual", "repository"] = "manual"
    content: str = Field(min_length=1, max_length=1_000_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=20, strict=True)
    metadata_filter: dict[str, Any] = Field(default_factory=dict)


def _require_rag_configuration(settings: Settings) -> None:
    if not settings.rag_enabled or not settings.embedding_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "rag_embedding_service_unavailable"},
        )


def _service(session: Session, membership: TenantMembership) -> RAGService:
    return RAGService(
        session,
        tenant_id=membership.tenant_id,
        actor_subject=membership.subject,
    )


@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def ingest_document(
    payload: DocumentIngestRequest,
    membership: Annotated[TenantMembership, Depends(require_documents_write)],
    session: Annotated[Session, Depends(get_tenant_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    _require_rag_configuration(settings)
    service = _service(session, membership)
    try:
        result = await service.ingest_document(
            title=payload.title,
            source_uri=payload.source_uri,
            source_type=payload.source_type,
            embedding_model=settings.embedding_model,
            content=payload.content,
            metadata=payload.metadata,
            embedder=OpenAICompatibleEmbeddingClient(settings),
            embedding_dimensions=settings.embedding_dimensions,
        )
        session.commit()
        return result
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EmbeddingServiceError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "embedding_provider_error"},
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "rag_persistence_unavailable"},
        ) from exc


@router.post("/search")
async def search_documents(
    payload: SearchRequest,
    membership: Annotated[TenantMembership, Depends(require_rag_search)],
    session: Annotated[Session, Depends(get_tenant_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    _require_rag_configuration(settings)
    try:
        return await _service(session, membership).search(
            query=payload.query,
            limit=payload.limit,
            metadata_filter=payload.metadata_filter,
            embedding_model=settings.embedding_model,
            embedder=OpenAICompatibleEmbeddingClient(settings),
            embedding_dimensions=settings.embedding_dimensions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EmbeddingServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "embedding_provider_error"},
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "rag_persistence_unavailable"},
        ) from exc


@router.get("/documents/{document_id}")
def get_document(
    document_id: UUID,
    membership: Annotated[TenantMembership, Depends(require_documents_read)],
    session: Annotated[Session, Depends(get_tenant_session)],
) -> dict[str, Any]:
    document = _service(session, membership).get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/documents/{document_id}/chunks/{chunk_id}")
def get_citation_source(
    document_id: UUID,
    chunk_id: UUID,
    membership: Annotated[TenantMembership, Depends(require_documents_read)],
    session: Annotated[Session, Depends(get_tenant_session)],
) -> dict[str, Any]:
    source = _service(session, membership).get_chunk_source(document_id, chunk_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Citation source not found")
    return source
