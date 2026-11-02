from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from ai_notebook_api.core.config import Settings, get_settings

router = APIRouter(tags=["health"])


@router.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/health/ready")
def readiness(
    response: Response, settings: Annotated[Settings, Depends(get_settings)]
) -> dict[str, object]:
    checks = {
        "persistence_configured": settings.persistence_configured,
        "authentication_configured": settings.auth_configured,
    }
    ready = all(checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready else "not_ready",
        "checks": checks,
        "note": "Configuration presence only; database connectivity and JWT verification are not yet implemented.",
    }
