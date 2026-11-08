from __future__ import annotations

import hashlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ai_notebook_api.core.config import Settings, get_settings
from ai_notebook_api.db.models import TenantMembership
from ai_notebook_api.db.session import get_tenant_session
from ai_notebook_api.rag.document_loader import (
    MAX_UPLOAD_BYTES,
    DocumentParseError,
    extract_document_text,
    safe_filename,
)
from ai_notebook_api.rag.embeddings import EmbeddingServiceError, OpenAICompatibleEmbeddingClient
from ai_notebook_api.rag.service import RAGService
from ai_notebook_api.security.tenant import require_tenant_permissions

router = APIRouter(prefix="/api/v1/rag", tags=["rag-documents"])
require_documents_write = require_tenant_permissions("documents:write")


@router.post("/documents/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    membership: Annotated[TenantMembership, Depends(require_documents_write)],
    session: Annotated[Session, Depends(get_tenant_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    if not settings.rag_enabled or not settings.embedding_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "rag_embedding_service_unavailable"},
        )

    try:
        raw_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(raw_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail={"code": "document_upload_too_large", "max_bytes": MAX_UPLOAD_BYTES},
            )

        filename = safe_filename(file.filename)
        extracted = extract_document_text(filename, raw_bytes, file.content_type)
        file_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        metadata = {
            "original_filename": filename,
            "uploaded_media_type": extracted.media_type,
            "file_sha256": file_sha256,
            "parser": extracted.parser,
        }
        service = RAGService(
            session,
            tenant_id=membership.tenant_id,
            actor_subject=membership.subject,
        )
        result = await service.ingest_document(
            title=filename,
            source_uri=f"urn:upload:sha256:{file_sha256}",
            source_type="upload",
            embedding_model=settings.embedding_model,
            content=extracted.text,
            metadata=metadata,
            embedder=OpenAICompatibleEmbeddingClient(settings),
            embedding_dimensions=settings.embedding_dimensions,
        )
        session.commit()
        result["file_sha256"] = file_sha256
        result["parser"] = extracted.parser
        return result
    except DocumentParseError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
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
    finally:
        await file.close()
