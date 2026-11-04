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

    @classmethod
    def from_environment(cls) -> Settings:
        raw_algorithms = os.getenv("AUTH_ALGORITHMS", "RS256")
        algorithms = tuple(
            dict.fromkeys(item.strip().upper() for item in raw_algorithms.split(",") if item.strip())
        )
        return cls(
            app_env=os.getenv("APP_ENV", "development").lower(),
            database_url=os.getenv("DATABASE_URL") or None,
            auth_jwks_url=os.getenv("AUTH_JWKS_URL") or None,
            auth_issuer=os.getenv("AUTH_ISSUER") or None,
            auth_audience=os.getenv("AUTH_AUDIENCE") or None,
            auth_algorithms=algorithms,
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
        return bool(modes and modes[-1].strip().lower() == "verify-full")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process; tests/deploy tooling can clear the cache."""
    return Settings.from_environment()
