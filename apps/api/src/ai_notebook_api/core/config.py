from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import parse_qs, urlparse

SUPPORTED_JWT_ALGORITHMS = frozenset({"RS256", "ES256"})


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "AI Notebook Studio API"
    app_env: str = "development"
    database_url: str | None = None
    auth_jwks_url: str | None = None
    auth_issuer: str | None = None
    auth_audience: str | None = None
    auth_algorithms: tuple[str, ...] = ("RS256",)
    ugai_enabled: bool = False
    ugai_base_url: str | None = None
    ugai_audience: str | None = None
    ugai_token_endpoint: str | None = None
    ugai_client_id: str | None = None
    ugai_client_secret: str | None = None

    @classmethod
    def from_environment(cls) -> Settings:
        raw_algorithms = os.getenv("AUTH_ALGORITHMS", "RS256")
        algorithms = tuple(
            dict.fromkeys(item.strip().upper() for item in raw_algorithms.split(",") if item.strip())
        )
        return cls(
            app_env=os.getenv("APP_ENV", "development").strip().lower(),
            database_url=os.getenv("DATABASE_URL") or None,
            auth_jwks_url=os.getenv("AUTH_JWKS_URL") or None,
            auth_issuer=os.getenv("AUTH_ISSUER") or None,
            auth_audience=os.getenv("AUTH_AUDIENCE") or None,
            auth_algorithms=algorithms,
            ugai_enabled=os.getenv("UGAI_ENABLED", "false").strip().lower() in {"1", "true", "yes"},
            ugai_base_url=os.getenv("UGAI_BASE_URL") or None,
            ugai_audience=os.getenv("UGAI_AUDIENCE") or None,
            ugai_token_endpoint=os.getenv("UGAI_TOKEN_ENDPOINT") or None,
            ugai_client_id=os.getenv("UGAI_CLIENT_ID") or None,
            ugai_client_secret=os.getenv("UGAI_CLIENT_SECRET") or None,
        )

    @property
    def auth_configured(self) -> bool:
        if not all((self.auth_jwks_url, self.auth_issuer, self.auth_audience)):
            return False
        try:
            jwks = urlparse(self.auth_jwks_url or "")
            issuer = urlparse(self.auth_issuer or "")
        except ValueError:
            return False
        return (
            jwks.scheme == "https"
            and bool(jwks.netloc)
            and not jwks.username
            and not jwks.password
            and issuer.scheme == "https"
            and bool(issuer.netloc)
            and not issuer.username
            and not issuer.password
            and bool(self.auth_algorithms)
            and set(self.auth_algorithms).issubset(SUPPORTED_JWT_ALGORITHMS)
        )

    @property
    def persistence_configured(self) -> bool:
        if not self.database_url:
            return False
        try:
            parsed = urlparse(self.database_url)
        except ValueError:
            return False
        return (
            parsed.scheme
            in {"postgres", "postgresql", "postgresql+psycopg"}
            and bool(parsed.netloc)
        )

    @property
    def database_tls_verified(self) -> bool:
        """Return true only when PostgreSQL verifies its CA and server hostname.

        sslmode=require encrypts transport but does not authenticate the server
        hostname. Production readiness therefore requires libpq's verify-full.
        """
        if not self.persistence_configured or not self.database_url:
            return False
        try:
            query = parse_qs(urlparse(self.database_url).query, keep_blank_values=True)
        except ValueError:
            return False
        modes = query.get("sslmode", [])
        return len(modes) == 1 and modes[0].strip().lower() == "verify-full"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process; tests/deploy tooling can clear the cache."""
    return Settings.from_environment()


def validate_ugai_configuration(settings: Settings) -> None:
    """Fail closed when production has no authenticated UGAI integration."""
    if settings.app_env == "production" and not settings.ugai_enabled:
        raise RuntimeError("UGAI_ENABLED=true is required in production")
    if not settings.ugai_enabled:
        return
    for name, value in (
        ("UGAI_BASE_URL", settings.ugai_base_url),
        ("UGAI_AUDIENCE", settings.ugai_audience),
        ("UGAI_TOKEN_ENDPOINT", settings.ugai_token_endpoint),
        ("UGAI_CLIENT_ID", settings.ugai_client_id),
        ("UGAI_CLIENT_SECRET", settings.ugai_client_secret),
    ):
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"{name} is required when UGAI integration is enabled")
    try:
        base = urlparse(settings.ugai_base_url or "")
        token = urlparse(settings.ugai_token_endpoint or "")
    except ValueError as exc:
        raise RuntimeError("UGAI endpoint configuration is invalid") from exc
    if (
        base.scheme != "https"
        or not base.hostname
        or base.username
        or base.password
        or base.path not in ("", "/")
        or base.query
        or base.fragment
        or token.scheme != "https"
        or not token.hostname
        or token.username
        or token.password
        or token.fragment
    ):
        raise RuntimeError("UGAI endpoints must be valid HTTPS endpoints")
    if any(ch.isspace() for ch in (settings.ugai_audience or "")):
        raise RuntimeError("UGAI_AUDIENCE is invalid")
