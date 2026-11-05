"""Tenant-authorized Notebook routes proxying the canonical UGAI task API.

The browser never receives UGAI credentials. The Notebook API verifies the
user, checks the active database membership and role, then exchanges the
verified user access token server-to-server for a scoped UGAI token.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials

from ai_notebook_api.db.models import TenantMembership
from ai_notebook_api.security.auth import (
    Principal,
    bearer_scheme,
    get_current_principal,
)
from ai_notebook_api.security.tenant import require_tenant_permissions
from ai_notebook_api.services.ugai_client import (
    TaskReceipt,
    TaskStatus,
    TaskSubmission,
    UGAIAuthenticationError,
    UGAITaskClient,
    UGAIUnavailable,
)

router = APIRouter(prefix="/api/v1", tags=["notebook-tasks"])

require_agents_run = require_tenant_permissions("agents:run")
require_notebooks_read = require_tenant_permissions("notebooks:read")


def get_ugai_task_client(request: Request) -> UGAITaskClient:
    client = getattr(request.app.state, "ugai_task_client", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "ugai_integration_unavailable"},
        )
    return client


def _user_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer access token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


def _map_ugai_error(exc: Exception) -> HTTPException:
    if isinstance(exc, UGAIAuthenticationError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "ugai_identity_exchange_failed"},
        )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "ugai_task_service_unavailable"},
    )


@router.post("/tasks", response_model=TaskReceipt, status_code=status.HTTP_202_ACCEPTED)
async def submit_notebook_task(
    submission: TaskSubmission,
    principal: Annotated[Principal, Depends(get_current_principal)],
    membership: Annotated[TenantMembership, Depends(require_agents_run)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    client: Annotated[UGAITaskClient, Depends(get_ugai_task_client)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    request_id: Annotated[UUID | None, Header(alias="X-Request-ID")] = None,
    correlation_id: Annotated[UUID | None, Header(alias="X-Correlation-ID")] = None,
):
    """Submit one task after active membership and agents:run permission checks."""
    if membership.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant membership mismatch")
    request_id = request_id or uuid4()
    try:
        return await client.submit_task(
            submission,
            subject=principal.subject,
            tenant_id=principal.tenant_id,
            subject_token=_user_token(credentials),
            request_id=request_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
    except (UGAIAuthenticationError, UGAIUnavailable) as exc:
        raise _map_ugai_error(exc) from exc


@router.get("/tasks/{task_id}", response_model=TaskStatus)
async def read_notebook_task(
    task_id: UUID,
    principal: Annotated[Principal, Depends(get_current_principal)],
    membership: Annotated[TenantMembership, Depends(require_notebooks_read)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    client: Annotated[UGAITaskClient, Depends(get_ugai_task_client)],
    request_id: Annotated[UUID | None, Header(alias="X-Request-ID")] = None,
):
    """Read task status only for users with active notebook-read permission."""
    if membership.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant membership mismatch")
    request_id = request_id or uuid4()
    try:
        return await client.get_task(
            task_id,
            subject=principal.subject,
            tenant_id=principal.tenant_id,
            subject_token=_user_token(credentials),
            request_id=request_id,
        )
    except (UGAIAuthenticationError, UGAIUnavailable) as exc:
        raise _map_ugai_error(exc) from exc


@router.post("/tasks/{task_id}/cancel", response_model=TaskStatus)
async def cancel_notebook_task(
    task_id: UUID,
    principal: Annotated[Principal, Depends(get_current_principal)],
    membership: Annotated[TenantMembership, Depends(require_agents_run)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    client: Annotated[UGAITaskClient, Depends(get_ugai_task_client)],
    request_id: Annotated[UUID | None, Header(alias="X-Request-ID")] = None,
):
    """Cancel only through UGAI's versioned, idempotent cancellation contract."""
    if membership.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant membership mismatch")
    request_id = request_id or uuid4()
    try:
        return await client.cancel_task(
            task_id,
            subject=principal.subject,
            tenant_id=principal.tenant_id,
            subject_token=_user_token(credentials),
            request_id=request_id,
        )
    except (UGAIAuthenticationError, UGAIUnavailable) as exc:
        raise _map_ugai_error(exc) from exc
