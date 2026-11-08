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


def _database_health(settings: Settings) -> tuple[bool, bool, bool, bool, bool]:
    """Check connectivity, schema, non-bypass runtime role, and tenant RLS policies."""
    if not settings.persistence_configured or not settings.database_url:
        return False, False, False, False, False
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

            role = connection.execute(
                text(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            ).mappings().first()
            runtime_role_owns_tenant_tables = connection.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = current_schema()
                          AND c.relname IN (
                              'tenant_memberships',
                              'audit_events',
                              'outbox_events',
                              'provider_credentials',
                              'rag_documents',
                              'rag_document_chunks'
                          )
                          AND c.relowner = (
                              SELECT oid FROM pg_roles WHERE rolname = current_user
                          )
                    )
                    """
                )
            ).scalar_one()
            runtime_role_safe = (
                role is not None
                and not bool(role["rolsuper"])
                and not bool(role["rolbypassrls"])
                and not bool(runtime_role_owns_tenant_tables)
            )

            required_privileges_present = connection.execute(
                text(
                    """
                    SELECT
                        has_schema_privilege(current_user, current_schema(), 'USAGE')
                        AND (
                        COALESCE(
                            has_table_privilege(
                                current_user,
                                to_regclass('tenant_memberships'),
                                'SELECT'
                            ),
                            false
                        )
                        AND (
                            NOT :rag_enabled
                            OR (
                                COALESCE(
                                    has_table_privilege(
                                        current_user,
                                        to_regclass('rag_documents'),
                                        'SELECT'
                                    ),
                                    false
                                )
                                AND COALESCE(
                                    has_table_privilege(
                                        current_user,
                                        to_regclass('rag_documents'),
                                        'INSERT'
                                    ),
                                    false
                                )
                                AND COALESCE(
                                    has_table_privilege(
                                        current_user,
                                        to_regclass('rag_document_chunks'),
                                        'SELECT'
                                    ),
                                    false
                                )
                                AND COALESCE(
                                    has_table_privilege(
                                        current_user,
                                        to_regclass('rag_document_chunks'),
                                        'INSERT'
                                    ),
                                    false
                                )
                            )
                        )
                        AND (
                            NOT :rag_enabled
                            OR COALESCE(
                                has_type_privilege(
                                    current_user,
                                    to_regtype('vector'),
                                    'USAGE'
                                ),
                                false
                            )
                        )
                        )
                    """
                ),
                {"rag_enabled": settings.rag_enabled},
            ).scalar_one()

            rag_rls_enforced = True
            if settings.rag_enabled:
                vector_extension_ready = connection.execute(
                    text(
                        "SELECT EXISTS ("
                        "SELECT 1 FROM pg_extension WHERE extname = 'vector' "
                        "AND string_to_array(extversion, '.')::integer[] >= ARRAY[0, 8, 0]::integer[]"
                        ")"
                    )
                ).scalar_one()
                rag_columns = set(
                    connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = current_schema() AND table_name = 'rag_documents'"
                        )
                    ).scalars()
                )
                schema_present = (
                    schema_present
                    and bool(vector_extension_ready)
                    and {"embedding_model", "metadata", "content_sha256"}.issubset(rag_columns)
                )

                protected_tables = connection.execute(
                    text(
                        """
                        SELECT count(*) = 2
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = current_schema()
                          AND c.relname IN ('rag_documents', 'rag_document_chunks')
                          AND c.relrowsecurity
                          AND c.relforcerowsecurity
                          AND EXISTS (
                              SELECT 1
                              FROM pg_policies p
                              WHERE p.schemaname = n.nspname
                                AND p.tablename = c.relname
                                AND p.policyname = CASE c.relname
                                    WHEN 'rag_documents' THEN 'rag_documents_tenant_isolation'
                                    ELSE 'rag_document_chunks_tenant_isolation'
                                END
                                AND p.qual LIKE '%app.tenant_id%'
                                AND p.with_check LIKE '%app.tenant_id%'
                          )
                        """
                    )
                ).scalar_one()
                required_indexes = connection.execute(
                    text(
                        """
                        SELECT count(*) = 3
                        FROM pg_indexes
                        WHERE schemaname = current_schema()
                          AND indexname IN (
                              'ix_rag_documents_metadata_gin',
                              'ix_rag_chunks_search_tsv',
                              'ix_rag_chunks_embedding_hnsw'
                          )
                        """
                    )
                ).scalar_one()
                rag_rls_enforced = bool(protected_tables) and bool(required_indexes)

        return (
            True,
            bool(schema_present),
            bool(runtime_role_safe),
            bool(rag_rls_enforced),
            bool(required_privileges_present),
        )
    except Exception:
        return False, False, False, False, False


@router.get("/health/ready")
def readiness(
    response: Response, settings: Annotated[Settings, Depends(get_settings)]
) -> dict[str, object]:
    (
        database_reachable,
        required_schema_present,
        runtime_role_safe,
        rag_rls_enforced,
        required_privileges_present,
    ) = _database_health(settings)
    jwks_reachable = identity_provider_ready(settings)
    checks = {
        "persistence_configured": settings.persistence_configured,
        "database_reachable": database_reachable,
        "required_schema_present": required_schema_present,
        "database_role_not_bypass_rls": runtime_role_safe,
        "database_required_privileges_present": required_privileges_present,
        "rag_rls_enforced": not settings.rag_enabled or rag_rls_enforced,
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
            "Readiness checks database connectivity, required schema, a non-superuser/non-BYPASSRLS "
            "runtime role, required tenant/RAG table privileges, forced tenant RLS and required RAG indexes when enabled, JWKS reachability, "
            "and enabled RAG/MCP configuration. It does not replace live token acceptance, cross-tenant "
            "integration tests, retrieval evaluation, or full production acceptance."
        ),
    }
