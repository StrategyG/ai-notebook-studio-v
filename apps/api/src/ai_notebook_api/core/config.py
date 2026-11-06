from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

SUPPORTED_JWT_ALGORITHMS = frozenset({"RS256", "ES256"})
RAG_EMBEDDING_DIMENSIONS = 1536


def _split_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))


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
    rag_enabled: bool = False
    embedding_api_url: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = RAG_EMBEDDING_DIMENSIONS
    embedding_timeout_seconds: float = 30.0
    mcp_enabled: bool = False
    mcp_resource_server_url: str | None = None
    mcp_allowed_hosts: tuple[str, ...] = ()
    mcp_allowed_origins: tuple[str, ...] = ()

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
            ugai_enabled=os.getenv("UGAI_ENABLED", "false").strip().lower() in {"1", "true", "yes"},
            ugai_base_url=os.getenv("UGAI_BASE_URL") or None,
            ugai_audience=os.getenv("UGAI_AUDIENCE") or None,
            ugai_token_endpoint=os.getenv("UGAI_TOKEN_ENDPOINT") or None,
            ugai_client_id=os.getenv("UGAI_CLIENT_ID") or None,
            ugai_client_secret=os.getenv("UGAI_CLIENT_SECRET") or None,
            rag_enabled=os.getenv("RAG_ENABLED", "false").strip().lower() in {"1", "true", "yes"},
            embedding_api_url=os.getenv("EMBEDDING_API_URL") or None,
            embedding_api_key=os.getenv("EMBEDDING_API_KEY") or None,
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            embedding_dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", str(RAG_EMBEDDING_DIMENSIONS))),
            embedding_timeout_seconds=float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "30")),
            mcp_enabled=os.getenv("MCP_ENABLED", "false").strip().lower() in {"1", "true", "yes"},
            mcp_resource_server_url=os.getenv("MCP_RESOURCE_SERVER_URL") or None,
            mcp_allowed_hosts=_split_csv(os.getenv("MCP_ALLOWED_HOSTS")),
            mcp_allowed_origins=_split_csv(os.getenv("MCP_ALLOWED_ORIGINS")),
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
        parsed = urlparse(self.database_url)
        return (
            parsed.scheme in {"postgres", "postgresql", "postgresql+psycopg"}
            and bool(parsed.netloc)
        )

    @property
    def embedding_configured(self) -> bool:
        if not all((self.embedding_api_url, self.embedding_api_key, self.embedding_model)):
            return False
        try:
            endpoint = urlparse(self.embedding_api_url or "")
        except ValueError:
            return False
        local_http_allowed = self.app_env != "production" and endpoint.scheme == "http" and (
            endpoint.hostname in {"localhost", "127.0.0.1", "::1"}
        )
        return (
            (endpoint.scheme == "https" or local_http_allowed)
            and bool(endpoint.hostname)
            and not endpoint.username
            and not endpoint.password
            and not endpoint.fragment
            and self.embedding_dimensions == RAG_EMBEDDING_DIMENSIONS
            and 1 <= self.embedding_timeout_seconds <= 120
        )

    @property
    def mcp_configured(self) -> bool:
        if not self.mcp_enabled:
            return True
        if (
            not self.auth_configured
            or not self.persistence_configured
            or not self.rag_enabled
            or not self.embedding_configured
            or not self.mcp_resource_server_url
            or not self.mcp_allowed_hosts
        ):
            return False
        try:
            resource = urlparse(self.mcp_resource_server_url)
            origins = [urlparse(origin) for origin in self.mcp_allowed_origins]
        except ValueError:
            return False
        return (
            resource.scheme == "https"
            and bool(resource.hostname)
            and not resource.username
            and not resource.password
            and resource.path.rstrip("/").endswith("/mcp")
            and not resource.query
            and not resource.fragment
            and (
                resource.hostname in self.mcp_allowed_hosts
                or f"{resource.hostname}:*" in self.mcp_allowed_hosts
            )
            and all(
                origin.scheme == "https"
                and bool(origin.netloc)
                and not origin.path.strip("/")
                and not origin.query
                and not origin.fragment
                for origin in origins
            )
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process; tests/deploy tooling can clear the cache."""
    return Settings.from_environment()


def validate_rag_configuration(settings: Settings) -> None:
    if settings.rag_enabled and not settings.embedding_configured:
        raise RuntimeError("RAG_ENABLED=true requires a valid embedding provider configuration")
    if settings.embedding_dimensions != RAG_EMBEDDING_DIMENSIONS:
        raise RuntimeError("The installed RAG schema requires 1536-dimensional embeddings")


def validate_mcp_configuration(settings: Settings) -> None:
    if settings.mcp_enabled and not settings.mcp_configured:
        raise RuntimeError(
            "MCP_ENABLED=true requires verified identity, PostgreSQL, RAG embeddings, "
            "an HTTPS resource URL, and explicit host allowlisting"
        )


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
