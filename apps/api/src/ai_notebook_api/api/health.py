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
    """Check connectivity and schema needed by the enabled persistence features."""
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
            membership_columns = set(
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = 'tenant_memberships'"
                    )
                ).scalars()
            )
            required_tables = set(_REQUIRED_TABLES)
            if settings.rag_enabled:
                required_tables.update({"rag_documents", "rag_document_chunks"})
            schema_present = required_tables.issubset(table_names) and "issuer" in membership_columns
            if settings.rag_enabled:
                vector_extension_present = connection.execute(
                    text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
                ).scalar_one()
                schema_present = schema_present and bool(vector_extension_present)
        return True, schema_present
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
        "rag_embedding_configured": not settings.rag_enabled or settings.embedding_configured,
        "mcp_configuration_valid": not settings.mcp_enabled or settings.mcp_configured,
    }
    ready = all(checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready else "not_ready",
        "checks": checks,
        "note": (
            "Readiness checks database connectivity, issuer-scoped identity schema, JWKS reachability, "
            "and the configuration/schema of enabled RAG and MCP features. It does not replace "
            "live token acceptance, cross-tenant integration tests, retrieval evaluation, or full "
            "production acceptance."
        ),
    }
