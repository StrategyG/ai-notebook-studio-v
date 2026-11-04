from typing import Annotated

from fastapi import APIRouter, Depends

from ai_notebook_api.db.models import TenantMembership
from ai_notebook_api.security.tenant import get_tenant_context

router = APIRouter(prefix="/api/v1/tenant", tags=["tenant"])


@router.get("/context")
def tenant_context(
    membership: Annotated[TenantMembership, Depends(get_tenant_context)],
) -> dict[str, str]:
    """Return only the tenant membership resolved from authoritative storage."""
    return {
        "tenant_id": str(membership.tenant_id),
        "subject": membership.subject,
        "role": membership.role,
        "status": membership.status,
    }
