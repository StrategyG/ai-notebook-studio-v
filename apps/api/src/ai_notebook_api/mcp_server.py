from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import AnyHttpUrl
from sqlalchemy.orm import Session, sessionmaker

from mcp.server.mcpserver import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings

from ai_notebook_api.core.config import Settings
from ai_notebook_api.db.session import get_engine
from ai_notebook_api.rag.embeddings import OpenAICompatibleEmbeddingClient
from ai_notebook_api.rag.service import RAGService
from ai_notebook_api.security.auth import TokenVerificationError, verify_access_token
from ai_notebook_api.security.tenant import (
    TENANT_ROLE_PERMISSIONS,
    TenantAuthorizationError,
    resolve_active_membership,
)

MCP_ALLOWED_TOOLS = frozenset({"rag_search", "rag_get_document"})


class JWTTokenVerifier(TokenVerifier):
    """MCP resource-server verifier backed by the API's configured JWT/JWKS verifier."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            principal = verify_access_token(token, self.settings)
        except TokenVerificationError:
            return None
        return AccessToken(
            token=token,
            client_id=f"{principal.issuer}|{principal.subject}",
            subject=principal.subject,
            scopes=sorted(principal.scopes),
            claims={
                "iss": principal.issuer,
                "sub": principal.subject,
                "tenant_id": str(principal.tenant_id),
                "roles": sorted(principal.roles),
            },
        )


def _open_authorized_session(
    settings: Settings,
    required_permissions: set[str],
    required_scopes: set[str],
) -> tuple[Session, Any]:
    token = get_access_token()
    if token is None:
        raise PermissionError("Authentication required")

    claims = token.claims or {}
    issuer = claims.get("iss")
    subject = token.subject or claims.get("sub")
    tenant_claim = claims.get("tenant_id")
    if (
        not isinstance(issuer, str)
        or not issuer
        or not isinstance(subject, str)
        or not subject
        or not isinstance(tenant_claim, str)
    ):
        raise PermissionError("Verified tenant identity required")
    try:
        tenant_id = UUID(tenant_claim)
    except ValueError as exc:
        raise PermissionError("Verified tenant identity required") from exc

    if not settings.persistence_configured or not settings.database_url:
        raise RuntimeError("Tenant persistence is unavailable")
    factory = sessionmaker(bind=get_engine(settings.database_url), expire_on_commit=False)
    session = factory()
    try:
        membership = resolve_active_membership(
            session,
            issuer=issuer,
            subject=subject,
            tenant_id=tenant_id,
        )
        granted = TENANT_ROLE_PERMISSIONS.get(membership.role, frozenset())
        if not required_permissions.issubset(granted):
            raise PermissionError("Tool permission denied")
        if not required_scopes.issubset(set(token.scopes)):
            raise PermissionError("Required MCP scope is missing")
        return session, membership
    except (TenantAuthorizationError, PermissionError):
        session.close()
        raise


def build_mcp_server(settings: Settings) -> tuple[MCPServer | None, Any | None]:
    """Build the authenticated Streamable HTTP MCP server when explicitly enabled."""
    if not settings.mcp_enabled:
        return None, None
    if not settings.mcp_configured:
        raise RuntimeError("MCP is enabled but its authentication, RAG, or host configuration is incomplete")

    server = MCPServer(
        "AI Notebook Studio RAG",
        token_verifier=JWTTokenVerifier(settings),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(settings.auth_issuer or ""),
            resource_server_url=AnyHttpUrl(settings.mcp_resource_server_url or ""),
            required_scopes=[],
            # The configured issuer uses its own audience identifier. The JWT verifier
            # validates AUTH_AUDIENCE; resource metadata still advertises the MCP URL.
            validate_token_resource=False,
        ),
    )

    @server.tool()
    async def rag_search(
        query: str,
        limit: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Search only documents owned by the authenticated tenant and return source citations."""
        if not settings.rag_enabled or not settings.embedding_configured:
            raise RuntimeError("RAG retrieval is unavailable")
        session, membership = _open_authorized_session(
            settings,
            {"mcp:tools:call", "rag:search"},
            {"rag:search"},
        )
        try:
            service = RAGService(
                session,
                tenant_id=membership.tenant_id,
                actor_subject=membership.subject,
            )
            return await service.search(
                query=query,
                limit=limit,
                metadata_filter=metadata_filter or {},
                embedder=OpenAICompatibleEmbeddingClient(settings),
                embedding_dimensions=settings.embedding_dimensions,
            )
        finally:
            session.close()

    @server.tool()
    async def rag_get_document(document_id: str) -> dict[str, Any]:
        """Read a document source and its SHA-256 provenance within the authenticated tenant."""
        if not settings.rag_enabled:
            raise RuntimeError("RAG retrieval is unavailable")
        try:
            parsed_document_id = UUID(document_id)
        except ValueError as exc:
            raise ValueError("document_id must be a UUID") from exc
        session, membership = _open_authorized_session(
            settings,
            {"mcp:tools:call", "documents:read"},
            {"documents:read"},
        )
        try:
            service = RAGService(
                session,
                tenant_id=membership.tenant_id,
                actor_subject=membership.subject,
            )
            document = service.get_document(parsed_document_id)
            if document is None:
                raise ValueError("Document not found")
            return document
        finally:
            session.close()

    transport_security = TransportSecuritySettings(
        allowed_hosts=list(settings.mcp_allowed_hosts),
        allowed_origins=list(settings.mcp_allowed_origins),
    )
    asgi_app = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        max_request_body_size=1_048_576,
        transport_security=transport_security,
    )
    return server, asgi_app
