from uuid import UUID

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from ai_notebook_api.core.config import Settings, get_settings
from ai_notebook_api.main import app
from ai_notebook_api.security import auth
from ai_notebook_api.security.auth import (
    MAX_BEARER_TOKEN_LENGTH,
    Principal,
    TokenVerificationError,
    require_scopes,
    verify_access_token,
)

client = TestClient(app)
TENANT_ID = "d2719d9a-3b0a-4b8a-a95b-1a8a1efc7f8e"
OIDC_ISSUER = "https://identity.example/"


def configured_settings() -> Settings:
    return Settings(
        auth_jwks_url="https://identity.example/.well-known/jwks.json",
        auth_issuer=OIDC_ISSUER,
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
    monkeypatch.setenv("AUTH_ISSUER", OIDC_ISSUER)
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

    monkeypatch.setattr(auth, "PyJWKClient", FakeJwksClient)
    auth._jwks_client.cache_clear()
    monkeypatch.setattr(jwt, "get_unverified_header", lambda _token: {"alg": "RS256"})
    observed = {}

    def fake_decode(token, key, **kwargs):
        observed.update(kwargs)
        assert token == "signed-token"
        assert key == "verified-public-key"
        return {
            "iss": OIDC_ISSUER,
            "sub": "user-123",
            "tenant_id": TENANT_ID,
            "roles": ["member"],
            "scope": "notebooks:read agents:run",
        }

    monkeypatch.setattr(jwt, "decode", fake_decode)
    principal = verify_access_token("signed-token", configured_settings())
    auth._jwks_client.cache_clear()

    assert principal == Principal(
        issuer=OIDC_ISSUER,
        subject="user-123",
        tenant_id=UUID(TENANT_ID),
        roles=frozenset({"member"}),
        scopes=frozenset({"notebooks:read", "agents:run"}),
    )
    assert observed["algorithms"] == ["RS256"]
    assert observed["issuer"] == OIDC_ISSUER
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
            "iss": OIDC_ISSUER,
            "aud": "ai-notebook-api",
            "exp": 2_000_000_000,
        },
    )
    with pytest.raises(TokenVerificationError, match="tenant_id"):
        verify_access_token("signed-token", configured_settings())


def test_verifier_rejects_issuer_not_matching_configured_provider(monkeypatch) -> None:
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
            "iss": "https://other-identity.example/",
            "aud": "ai-notebook-api",
            "exp": 2_000_000_000,
            "tenant_id": TENANT_ID,
        },
    )
    with pytest.raises(TokenVerificationError, match="issuer"):
        verify_access_token("signed-token", configured_settings())


def test_scope_dependency_rejects_missing_scope() -> None:
    dependency = require_scopes("notebooks:write")
    principal = Principal(
        issuer=OIDC_ISSUER,
        subject="user-123",
        tenant_id=UUID(TENANT_ID),
        roles=frozenset({"member"}),
        scopes=frozenset({"notebooks:read"}),
    )
    with pytest.raises(HTTPException) as error:
        dependency(principal)
    assert error.value.status_code == 403



def test_verifier_rejects_oversized_bearer_tokens_before_jwks_lookup() -> None:
    with pytest.raises(TokenVerificationError, match="size"):
        verify_access_token("x" * (MAX_BEARER_TOKEN_LENGTH + 1), configured_settings())


@pytest.mark.parametrize(
    "claims,expected",
    [
        (
            {
                "iss": OIDC_ISSUER,
                "sub": "user-123",
                "tenant_id": TENANT_ID,
                "roles": "admin",
                "scope": "rag:search",
            },
            "roles",
        ),
        (
            {
                "iss": OIDC_ISSUER,
                "sub": "user-123",
                "tenant_id": TENANT_ID,
                "roles": ["admin"],
                "scope": ["rag:search"],
            },
            "scope",
        ),
        (
            {
                "iss": OIDC_ISSUER,
                "sub": "user-123",
                "tenant_id": "not-a-uuid",
                "roles": ["admin"],
                "scope": "rag:search",
            },
            "verification",
        ),
        (
            {
                "iss": OIDC_ISSUER,
                "sub": "x" * 256,
                "tenant_id": TENANT_ID,
                "roles": ["admin"],
                "scope": "rag:search",
            },
            "subject",
        ),
    ],
)
def test_verifier_rejects_malformed_claim_shapes(monkeypatch, claims, expected) -> None:
    class FakeSigningKey:
        key = "public-key"

    class FakeJwksClient:
        def get_signing_key_from_jwt(self, _token):
            return FakeSigningKey()

    monkeypatch.setattr(auth, "_jwks_client", lambda _url: FakeJwksClient())
    monkeypatch.setattr(jwt, "get_unverified_header", lambda _token: {"alg": "RS256"})
    monkeypatch.setattr(jwt, "decode", lambda *_args, **_kwargs: claims)

    with pytest.raises(TokenVerificationError, match=expected):
        verify_access_token("signed-token", configured_settings())


def test_identity_provider_readiness_checks_jwks_keys(monkeypatch) -> None:
    class AvailableJwks:
        def get_signing_keys(self):
            return [object()]

    class EmptyJwks:
        def get_signing_keys(self):
            return []

    monkeypatch.setattr(auth, "_jwks_client", lambda _url: AvailableJwks())
    assert auth.identity_provider_ready(configured_settings()) is True

    monkeypatch.setattr(auth, "_jwks_client", lambda _url: EmptyJwks())
    assert auth.identity_provider_ready(configured_settings()) is False
    assert auth.identity_provider_ready(Settings()) is False


def test_current_principal_rejects_missing_or_wrong_bearer_credentials() -> None:
    settings = configured_settings()

    with pytest.raises(HTTPException) as missing:
        auth.get_current_principal(None, settings)
    assert missing.value.status_code == 401

    wrong_scheme = HTTPAuthorizationCredentials(scheme="Basic", credentials="secret")
    with pytest.raises(HTTPException) as invalid_scheme:
        auth.get_current_principal(wrong_scheme, settings)
    assert invalid_scheme.value.status_code == 401


def test_current_principal_fails_closed_when_identity_provider_is_not_configured() -> None:
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="signed-token")

    with pytest.raises(HTTPException) as error:
        auth.get_current_principal(credentials, Settings())

    assert error.value.status_code == 503


def test_current_principal_rejects_invalid_verified_token(monkeypatch) -> None:
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid-token")
    monkeypatch.setattr(
        auth,
        "verify_access_token",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TokenVerificationError("invalid")),
    )

    with pytest.raises(HTTPException) as error:
        auth.get_current_principal(credentials, configured_settings())

    assert error.value.status_code == 401
    assert error.value.headers["WWW-Authenticate"] == "Bearer"



def test_identity_provider_readiness_fails_closed_when_jwks_fetch_raises(monkeypatch) -> None:
    class BrokenJwks:
        def get_signing_keys(self):
            raise ConnectionError("private identity provider details")

    monkeypatch.setattr(auth, "_jwks_client", lambda _url: BrokenJwks())

    assert auth.identity_provider_ready(configured_settings()) is False
