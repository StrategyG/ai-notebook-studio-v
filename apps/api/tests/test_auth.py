from uuid import UUID

from fastapi import HTTPException
from fastapi.testclient import TestClient
import jwt
import pytest

from ai_notebook_api.core.config import Settings, get_settings
from ai_notebook_api.main import app
from ai_notebook_api.security import auth
from ai_notebook_api.security.auth import Principal, TokenVerificationError, verify_access_token

client = TestClient(app)
TENANT_ID = "d2719d9a-3b0a-4b8a-a95b-1a8a1efc7f8e"


def configured_settings() -> Settings:
    return Settings(
        auth_jwks_url="https://identity.example/.well-known/jwks.json",
        auth_issuer="https://identity.example/",
        auth_audience="ai-notebook-api",
        auth_algorithms=("RS256",),
    )


def test_identity_endpoint_is_unavailable_when_auth_is_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("AUTH_JWKS_URL", raising=False)
    monkeypatch.delenv("AUTH_ISSUER", raising=False)
    monkeypatch.delenv("AUTH_AUDIENCE", raising=False)
    get_settings.cache_clear()
    response = client.get("/api/v1/me")
    assert response.status_code == 503
    get_settings.cache_clear()


def test_identity_endpoint_requires_bearer_token(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_JWKS_URL", "https://identity.example/jwks")
    monkeypatch.setenv("AUTH_ISSUER", "https://identity.example/")
    monkeypatch.setenv("AUTH_AUDIENCE", "ai-notebook-api")
    get_settings.cache_clear()
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    get_settings.cache_clear()


def test_verifier_uses_allowlisted_algorithm_and_required_claim_validation(monkeypatch) -> None:
    class FakeSigningKey:
        key = "verified-public-key"

    class FakeJwksClient:
        def __init__(self, url: str, **kwargs) -> None:
            assert url == "https://identity.example/.well-known/jwks.json"
            assert kwargs["timeout"] == 5

        def get_signing_key_from_jwt(self, token: str) -> FakeSigningKey:
            assert token == "signed-token"
            return FakeSigningKey()

    monkeypatch.setattr(auth, "_jwks_client", lambda url: FakeJwksClient(url))
    monkeypatch.setattr(jwt, "get_unverified_header", lambda _token: {"alg": "RS256"})
    observed = {}

    def fake_decode(token, key, **kwargs):
        observed.update(kwargs)
        assert token == "signed-token"
        assert key == "verified-public-key"
        return {
            "sub": "user-123",
            "tenant_id": TENANT_ID,
            "roles": ["member"],
            "scope": "notebooks:read agents:run",
        }

    monkeypatch.setattr(jwt, "decode", fake_decode)
    principal = verify_access_token("signed-token", configured_settings())

    assert principal == Principal(
        subject="user-123",
        tenant_id=UUID(TENANT_ID),
        roles=frozenset({"member"}),
        scopes=frozenset({"notebooks:read", "agents:run"}),
    )
    assert observed["algorithms"] == ["RS256"]
    assert observed["issuer"] == "https://identity.example/"
    assert observed["audience"] == "ai-notebook-api"
    assert set(observed["options"]["require"]) == {"exp", "iss", "aud", "sub"}


def test_verifier_rejects_unapproved_algorithm_before_key_lookup(monkeypatch) -> None:
    monkeypatch.setattr(jwt, "get_unverified_header", lambda _token: {"alg": "none"})
    with pytest.raises(TokenVerificationError, match="algorithm"):
        verify_access_token("unsigned-token", configured_settings())


def test_verifier_requires_tenant_claim(monkeypatch) -> None:
    class FakeSigningKey:
        key = "public-key"

    class FakeJwksClient:
        def get_signing_key_from_jwt(self, _token):
            return FakeSigningKey()

    monkeypatch.setattr(auth, "_jwks_client", lambda _url: FakeJwksClient())
    monkeypatch.setattr(jwt, "get_unverified_header", lambda _token: {"alg": "RS256"})
    monkeypatch.setattr(
        jwt,
        "decode",
        lambda *_args, **_kwargs: {
            "sub": "user-123",
            "iss": "https://identity.example/",
            "aud": "ai-notebook-api",
            "exp": 2_000_000_000,
        },
    )
    with pytest.raises(TokenVerificationError, match="tenant_id"):
        verify_access_token("signed-token", configured_settings())


def test_scope_dependency_rejects_missing_scope() -> None:
    from ai_notebook_api.security.auth import require_scopes

    dependency = require_scopes("notebooks:write")
    principal = Principal(
        subject="user-123",
        tenant_id=UUID(TENANT_ID),
        roles=frozenset({"member"}),
        scopes=frozenset({"notebooks:read"}),
    )
    with pytest.raises(HTTPException) as error:
        dependency(principal)
    assert error.value.status_code == 403
