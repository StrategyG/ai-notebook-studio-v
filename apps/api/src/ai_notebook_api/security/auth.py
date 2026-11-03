from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from ai_notebook_api.core.config import Settings, get_settings

bearer_scheme = HTTPBearer(auto_error=False)
MAX_BEARER_TOKEN_LENGTH = 16_384
MAX_ROLE_COUNT = 64
MAX_SCOPE_COUNT = 128


class TokenVerificationError(ValueError):
    """Raised when an access token cannot be verified or mapped to a principal."""


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    tenant_id: UUID
    roles: frozenset[str]
    scopes: frozenset[str]


@lru_cache(maxsize=16)
def _jwks_client(url: str) -> PyJWKClient:
    # URL is deployment-controlled configuration, never supplied by the caller.
    return PyJWKClient(url, timeout=5, cache_jwk_set=True, lifespan=300)


def verify_access_token(token: str, settings: Settings) -> Principal:
    if not settings.auth_configured:
        raise TokenVerificationError("identity verification is not configured")
    if not token or len(token) > MAX_BEARER_TOKEN_LENGTH:
        raise TokenVerificationError("access token size is invalid")

    try:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        if algorithm not in settings.auth_algorithms:
            raise TokenVerificationError("token signing algorithm is not allowed")

        signing_key = _jwks_client(settings.auth_jwks_url or "").get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=list(settings.auth_algorithms),
            audience=settings.auth_audience,
            issuer=settings.auth_issuer,
            options={"require": ["exp", "iss", "aud", "sub"]},
            leeway=30,
        )
        subject = claims.get("sub")
        tenant_claim = claims.get("tenant_id")
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise TokenVerificationError("token subject is invalid")
        if not isinstance(tenant_claim, str):
            raise TokenVerificationError("token must contain a tenant_id claim")
        tenant_id = UUID(tenant_claim)

        raw_roles = claims.get("roles", [])
        raw_scopes = claims.get("scope", "")
        if (
            not isinstance(raw_roles, list)
            or len(raw_roles) > MAX_ROLE_COUNT
            or any(not isinstance(item, str) or not item or len(item) > 128 for item in raw_roles)
        ):
            raise TokenVerificationError("token roles claim is invalid")
        if not isinstance(raw_scopes, str) or len(raw_scopes) > 4096:
            raise TokenVerificationError("token scope claim is invalid")
        scopes = frozenset(raw_scopes.split())
        if len(scopes) > MAX_SCOPE_COUNT or any(len(scope) > 128 for scope in scopes):
            raise TokenVerificationError("token scope claim exceeds the allowed limit")

        return Principal(
            subject=subject,
            tenant_id=tenant_id,
            roles=frozenset(raw_roles),
            scopes=scopes,
        )
    except TokenVerificationError:
        raise
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
        raise TokenVerificationError("access token verification failed") from exc


def identity_provider_ready(settings: Settings) -> bool:
    """Check that the configured JWKS endpoint is reachable and exposes signing keys."""
    if not settings.auth_configured:
        return False
    try:
        return bool(_jwks_client(settings.auth_jwks_url or "").get_signing_keys())
    except Exception:
        # Readiness must fail closed without exposing identity-provider details.
        return False


def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    if not settings.auth_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured on this deployment",
        )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer access token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return verify_access_token(credentials.credentials, settings)
    except TokenVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_scopes(*required_scopes: str):
    if not required_scopes or any(not scope or len(scope) > 128 for scope in required_scopes):
        raise ValueError("at least one valid scope is required")

    def dependency(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> Principal:
        if not set(required_scopes).issubset(principal.scopes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient scope",
            )
        return principal

    return dependency
