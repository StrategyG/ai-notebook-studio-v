from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from mcp.client import Client
from mcp.server.auth.provider import AccessToken

from ai_notebook_api import mcp_server
from ai_notebook_api.core.config import Settings
from ai_notebook_api.main import app
from ai_notebook_api.mcp_server import (
       JWTTokenVerifier,
    MCP_ALLOWED_TOOLS,
    _open_authorized_session,
        _register_allowlisted_tool,
    _validate_required_scopes,
    build_mcp_server,
)
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
        mcp_allowed_hosts=("testserver", "testserver:80"),
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


def test_mcp_configuration_rejects_host_not_bound_to_resource_url() -> None:
    settings = configured_mcp_settings()
    settings = Settings(
        **{
            field: ("attacker.example",) if field == "mcp_allowed_hosts" else getattr(settings, field)
            for field in settings.__dataclass_fields__
        }
    )
    assert settings.mcp_configured is False


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


def test_mcp_tool_registration_enforces_the_explicit_allowlist() -> None:
    class FakeServer:
        def __init__(self) -> None:
            self.registered: list[str] = []

        def tool(self):
            def register(handler):
                self.registered.append(handler.__name__)
                return handler

            return register

    async def rag_search():
        return {}

    async def rag_get_document():
        return {}

    async def arbitrary_shell():
        return {}

    server = FakeServer()
    _register_allowlisted_tool(server, rag_search)
    _register_allowlisted_tool(server, rag_get_document)

    assert server.registered == ["rag_search", "rag_get_document"]
    with pytest.raises(RuntimeError, match="not allowlisted"):
        _register_allowlisted_tool(server, arbitrary_shell)


def test_mcp_tools_require_their_own_narrow_token_scopes() -> None:
    search_token = AccessToken(
        token="verified-search-token",
        client_id="identity.example|user-1",
        scopes=["mcp:tools:call", "rag:search"],
    )
    document_token = AccessToken(
        token="verified-document-token",
        client_id="identity.example|user-1",
        scopes=["mcp:tools:call", "documents:read"],
    )

    _validate_required_scopes(search_token, {"rag:search"})
    _validate_required_scopes(document_token, {"documents:read"})

    with pytest.raises(PermissionError, match="scope"):
        _validate_required_scopes(search_token, {"documents:read"})
    with pytest.raises(PermissionError, match="scope"):
        _validate_required_scopes(document_token, {"rag:search"})
    with pytest.raises(ValueError, match="at least one"):
        _validate_required_scopes(search_token, set())



def _verified_access_token(*, scopes: list[str] | None = None) -> AccessToken:
    return AccessToken(
        token="verified-test-token",
        client_id="https://identity.example/|user-1",
        subject="user-1",
        scopes=scopes or ["mcp:tools:call", "rag:search", "documents:read"],
        claims={
            "iss": "https://identity.example/",
            "sub": "user-1",
            "tenant_id": "d2719d9a-3b0a-4b8a-a95b-1a8a1efc7f8e",
        },
    )


class FakeMcpSession:
    def __init__(self):
        self.committed = False
        self.closed = False

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def _patch_mcp_session(monkeypatch, *, role: str = "viewer"):
    sessions: list[FakeMcpSession] = []
    membership = SimpleNamespace(
        tenant_id=UUID("d2719d9a-3b0a-4b8a-a95b-1a8a1efc7f8e"),
        subject="user-1",
        role=role,
    )

    def factory(**_kwargs):
        def create_session():
            session = FakeMcpSession()
            sessions.append(session)
            return session

        return create_session

    monkeypatch.setattr(mcp_server, "get_engine", lambda _url: object())
    monkeypatch.setattr(mcp_server, "sessionmaker", factory)
    monkeypatch.setattr(mcp_server, "resolve_active_membership", lambda *_args, **_kwargs: membership)
    return sessions, membership


def test_mcp_authorized_session_fails_closed_without_access_token(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: None)

    with pytest.raises(PermissionError, match="Authentication required"):
        _open_authorized_session(
            configured_mcp_settings(),
            {"mcp:tools:call", "rag:search"},
            {"rag:search"},
        )


@pytest.mark.parametrize(
    "claims",
    [
        {},
        {"iss": "https://identity.example/", "sub": "user-1"},
        {"iss": "", "sub": "user-1", "tenant_id": "d2719d9a-3b0a-4b8a-a95b-1a8a1efc7f8e"},
        {"iss": "https://identity.example/", "sub": "", "tenant_id": "d2719d9a-3b0a-4b8a-a95b-1a8a1efc7f8e"},
        {"iss": "https://identity.example/", "sub": "user-1", "tenant_id": "not-a-uuid"},
    ],
)
def test_mcp_authorized_session_rejects_unverified_or_malformed_tenant_identity(
    monkeypatch, claims
) -> None:
    token = AccessToken(
        token="verified-test-token",
        client_id="identity|user",
        subject=claims.get("sub"),
        scopes=["mcp:tools:call", "rag:search"],
        claims=claims,
    )
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: token)

    with pytest.raises(PermissionError, match="identity"):
        _open_authorized_session(
            configured_mcp_settings(),
            {"mcp:tools:call", "rag:search"},
            {"rag:search"},
        )


def test_mcp_authorized_session_rejects_unconfigured_database(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: _verified_access_token())

    with pytest.raises(RuntimeError, match="persistence"):
        _open_authorized_session(
            Settings(),
            {"mcp:tools:call", "rag:search"},
            {"rag:search"},
        )


def test_mcp_authorized_session_checks_database_role_and_token_scopes(monkeypatch) -> None:
    sessions, _membership = _patch_mcp_session(monkeypatch)
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: _verified_access_token())

    session, membership = _open_authorized_session(
        configured_mcp_settings(),
        {"mcp:tools:call", "rag:search"},
        {"rag:search"},
    )

    assert membership.role == "viewer"
    assert session.committed is True
    assert session.closed is False

    with pytest.raises(PermissionError, match="permission"):
        _open_authorized_session(
            configured_mcp_settings(),
            {"documents:write"},
            {"documents:read"},
        )
    assert sessions[-1].closed is True

    monkeypatch.setattr(
        mcp_server,
        "get_access_token",
        lambda: _verified_access_token(scopes=["mcp:tools:call"]),
    )
    with pytest.raises(PermissionError, match="scope"):
        _open_authorized_session(
            configured_mcp_settings(),
            {"mcp:tools:call", "rag:search"},
            {"rag:search"},
        )
    assert sessions[-1].closed is True
    session.close()


@pytest.mark.asyncio
async def test_mcp_search_and_document_tools_use_authorized_tenant_session(monkeypatch) -> None:
    sessions, _membership = _patch_mcp_session(monkeypatch)
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: _verified_access_token())

    class FakeRAGService:
        def __init__(self, _session, *, tenant_id, actor_subject):
            assert tenant_id == UUID("d2719d9a-3b0a-4b8a-a95b-1a8a1efc7f8e")
            assert actor_subject == "user-1"

        async def search(self, **kwargs):
            assert kwargs["query"] == "tenant isolation"
            assert kwargs["embedding_model"] == "test-model"
            return {"query": kwargs["query"], "results": [], "citations": []}

        def get_document(self, document_id):
            return {"document_id": str(document_id), "content_hash_valid": True}

    monkeypatch.setattr(mcp_server, "RAGService", FakeRAGService)
    monkeypatch.setattr(mcp_server, "OpenAICompatibleEmbeddingClient", lambda _settings: object())
    server, _asgi_app = build_mcp_server(configured_mcp_settings())
    assert server is not None

    async with Client(server) as client:
        search_result = await client.call_tool(
            "rag_search",
            {"query": "tenant isolation", "limit": 3, "metadata_filter": {"area": "security"}},
        )
        document_result = await client.call_tool(
            "rag_get_document",
            {"document_id": "d9d50c4a-5c50-4bb6-bfa0-7e9d00c33c12"},
        )

    assert search_result.isError is not True
    assert document_result.isError is not True
    assert len(sessions) == 2
    assert all(session.committed and session.closed for session in sessions)
