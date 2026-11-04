from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text

from ai_notebook_api.core.config import Settings, get_settings
from ai_notebook_api.db.session import get_engine
from ai_notebook_api.security.auth import identity_provider_ready

router = APIRouter(tags=["health"])

_REQUIRED_TABLES = frozenset(
    {"tenant_memberships", "audit_events", "outbox_events", "provider_credentials"}
)


@router.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "alive"}


def _database_health(settings: Settings) -> tuple[bool, bool]:
    """Return database connectivity and required-schema presence without leaking errors."""
    if not settings.persistence_configured or not settings.database_url:
        return False, False
    try:
        engine = get_engine(settings.database_url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            table_names = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = current_schema()"
                    )
                ).scalars()
            )
        return True, _REQUIRED_TABLES.issubset(table_names)
    except Exception:
        return False, False


@router.get("/health/ready")
def readiness(
    response: Response, settings: Annotated[Settings, Depends(get_settings)]
) -> dict[str, object]:
    database_reachable, required_schema_present = _database_health(settings)
    jwks_reachable = identity_provider_ready(settings)
    checks = {
        "persistence_configured": settings.persistence_configured,
        "database_reachable": database_reachable,
        "required_schema_present": required_schema_present,
        "authentication_configured": settings.auth_configured,
        "jwks_reachable": jwks_reachable,
        "production_database_tls_policy": (
            settings.app_env != "production" or settings.database_tls_verified
        ),
    }
    ready = all(checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready else "not_ready",
        "checks": checks,
        "note": (
            "Readiness verifies database connectivity, required base tables, JWKS reachability "
            "and the production PostgreSQL TLS policy. Production requires sslmode=verify-full. "
            "It does not replace migration-version checks, live token acceptance, tenant-isolation "
            "tests, or full production acceptance."
        ),
    }
