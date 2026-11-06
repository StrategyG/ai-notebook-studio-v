from typing import Annotated

from fastapi import APIRouter, Depends

from ai_notebook_api.security.auth import Principal, get_current_principal

router = APIRouter(prefix="/api/v1", tags=["identity"])


@router.get("/me")
def current_identity(
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> dict[str, object]:
    """Return verified identity claims; never return the bearer token."""
    return {
        "issuer": principal.issuer,
        "subject": principal.subject,
        "tenant_id": str(principal.tenant_id),
        "roles": sorted(principal.roles),
        "scopes": sorted(principal.scopes),
    }
