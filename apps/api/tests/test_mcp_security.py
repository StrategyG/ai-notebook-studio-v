from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from mcp.client import Client

from ai_notebook_api.core.config import Settings
from ai_notebook_api.main import app
from ai_notebook_api.mcp_server import MCP_ALLOWED_TOOLS, JWTTokenVerifier, build_mcp_server
from ai_notebook_api.security.auth import Principal, TokenVerificationError


def configured_mcp_settings() -> Settings:
    return Settings(
        database_url="postgresql://app:password@db.example:5432/notebook",
        auth_jwks_url="https://identity.example/.well-known/jwks.json",
        auth_issuer="https://identity.example/",
        auth_audience="ai-notebook-api",
        rag_enabled=True,
        embedding_api_url="https://embedding.example/v1/embeddings",
        embedding_api_key="test-key",
        embedding_model="test-model",
        embedding_dimensions=1536,
        mcp_enabled=True,
        mcp_resource_server_url="https://testserver/mcp",
        mcp_allowed_hosts=("testserver:80",),
    )


@pytest.mark.asyncio
async def test_mcp_token_verifier_maps_only_verified_issuer_scoped_identity(monkeypatch) -> None:
    principal = Principal(
        issuer="https://identity.example/",
        subject="user-1",
        tenant_id=UUID("d2719d9a-3b0a-4b8a-a95b-1a8a1efc7f8e"),
        roles=frozenset({"viewer"}),
        scopes=frozenset({"rag:search"}),
    )
    monkeypatch.setattr(
        "ai_notebook_api.mcp_server.verify_access_token",
        lambda token, _settings: principal if token == "valid-token" else (_ for _ in ()).throw(
            TokenVerificationError("invalid token")
        ),
    )
    verifier = JWTTokenVerifier(configured_mcp_settings())

    access_token = await verifier.verify_token("valid-token")

    assert access_token is not None
    assert access_token.subject == "user-1"
    assert access_token.scopes == ["rag:search"]
    assert access_token.claims == {
        "iss": "https://identity.example/",
        "sub": "user-1",
        "tenant_id": "d2719d9a-3b0a-4b8a-a95b-1a8a1efc7f8e",
        "roles": ["viewer"],
    }


@pytest.mark.asyncio
async def test_mcp_token_verifier_rejects_invalid_tokens(monkeypatch) -> None:
    monkeypatch.setattr(
        "ai_notebook_api.mcp_server.verify_access_token",
        lambda _token, _settings: (_ for _ in ()).throw(TokenVerificationError("invalid")),
    )
    verifier = JWTTokenVerifier(configured_mcp_settings())

    assert await verifier.verify_token("invalid-token") is None


def test_mcp_tool_allowlist_is_explicit_and_read_only() -> None:
    assert MCP_ALLOWED_TOOLS == frozenset({"rag_search", "rag_get_document"})


def test_mcp_server_is_not_created_when_disabled() -> None:
    assert build_mcp_server(Settings()) == (None, None)


def test_mcp_configuration_fails_closed_without_host_allowlist() -> None:
    settings = configured_mcp_settings()
    settings = Settings(
        **{
            field: getattr(settings, field)
            for field in settings.__dataclass_fields__
            if field != "mcp_allowed_hosts"
        }
    )
    with pytest.raises(RuntimeError, match="configuration is incomplete"):
        build_mcp_server(settings)


def test_mcp_http_endpoint_requires_bearer_authentication() -> None:
    server, asgi_app = build_mcp_server(configured_mcp_settings())
    assert server is not None
    assert asgi_app is not None

    with TestClient(asgi_app) as client:
        response = client.post("/mcp", headers={"Host": "testserver:80"}, json={})

    assert response.status_code == 401


def test_disabled_mcp_endpoint_returns_service_unavailable() -> None:
    response = TestClient(app).post("/mcp", json={})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "mcp_not_enabled"


@pytest.mark.asyncio
async def test_mcp_server_registers_only_the_allowlisted_tools() -> None:
    server, _asgi_app = build_mcp_server(configured_mcp_settings())
    assert server is not None

    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}

    assert names == MCP_ALLOWED_TOOLS
