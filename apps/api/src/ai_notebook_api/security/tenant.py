from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_notebook_api.db.models import TenantMembership
from ai_notebook_api.db.session import apply_tenant_database_context, get_tenant_session
from ai_notebook_api.security.auth import Principal, get_current_principal


class TenantAuthorizationError(ValueError):
    """The authenticated issuer-scoped subject is not an active tenant member."""


TENANT_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": frozenset(
        {
            "tenant:read",
            "tenant:manage",
            "members:manage",
            "projects:manage",
            "notebooks:read",
            "notebooks:write",
            "agents:run",
            "providers:manage",
            "documents:read",
            "documents:write",
            "rag:search",
            "mcp:tools:call",
        }
    ),
    "admin": frozenset(
        {
            "tenant:read",
            "members:manage",
            "projects:manage",
            "notebooks:read",
            "notebooks:write",
            "agents:run",
            "providers:manage",
            "documents:read",
            "documents:write",
            "rag:search",
            "mcp:tools:call",
        }
    ),
    "editor": frozenset(
        {
            "tenant:read",
            "notebooks:read",
            "notebooks:write",
            "agents:run",
            "documents:read",
            "documents:write",
            "rag:search",
            "mcp:tools:call",
        }
    ),
    "member": frozenset(
        {
            "tenant:read",
            "notebooks:read",
            "agents:run",
            "documents:read",
            "rag:search",
            "mcp:tools:call",
        }
    ),
    "viewer": frozenset(
        {
            "tenant:read",
            "notebooks:read",
            "documents:read",
            "rag:search",
            "mcp:tools:call",
        }
    ),
}


def resolve_active_membership(
    session: Session, *, issuer: str, subject: str, tenant_id: UUID
) -> TenantMembership:
    if not issuer or len(issuer) > 2048 or not subject or len(subject) > 255:
        raise TenantAuthorizationError("issuer-scoped principal identity is invalid")
    apply_tenant_database_context(session, str(tenant_id))
    membership = session.scalar(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.issuer == issuer,
            TenantMembership.subject == subject,
            TenantMembership.status == "active",
        )
    )
    if membership is None:
        raise TenantAuthorizationError("active tenant membership required")
    return membership


def get_tenant_context(
    principal: Annotated[Principal, Depends(get_current_principal)],
    session: Annotated[Session, Depends(get_tenant_session)],
) -> TenantMembership:
    try:
        membership = resolve_active_membership(
            session,
            issuer=principal.issuer,
            subject=principal.subject,
            tenant_id=principal.tenant_id,
        )
        # Release the DB transaction before endpoint code calls external services
        # such as embeddings or UGAI. The session factory uses expire_on_commit=False;
        # data access must re-apply the transaction-local tenant GUC.
        session.commit()
        return membership
    except TenantAuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active tenant membership required",
        ) from exc


def require_tenant_permissions(*required_permissions: str):
    if not required_permissions or any(
        not permission or len(permission) > 128 for permission in required_permissions
    ):
        raise ValueError("at least one valid tenant permission is required")

    def dependency(
        membership: Annotated[TenantMembership, Depends(get_tenant_context)],
    ) -> TenantMembership:
        granted = TENANT_ROLE_PERMISSIONS.get(membership.role, frozenset())
        if not set(required_permissions).issubset(granted):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient tenant role permissions",
            )
        return membership

    return dependency
