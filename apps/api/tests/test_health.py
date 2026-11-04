from fastapi.testclient import TestClient

from ai_notebook_api.core.config import Settings, get_settings
from ai_notebook_api.main import app

client = TestClient(app)


def test_liveness_is_available_without_external_services() -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_does_not_claim_ready_without_auth_and_database(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    get_settings.cache_clear()
    response = client.get("/health/ready")
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["checks"]["persistence_configured"] is False
    assert payload["checks"]["authentication_configured"] is False
    get_settings.cache_clear()


def test_readiness_rejects_non_https_identity_endpoints(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setattr(
        "ai_notebook_api.api.health._database_health",
        lambda _settings: (True, True),
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example:5432/app")
    monkeypatch.setenv("AUTH_JWKS_URL", "http://identity.example/.well-known/jwks.json")
    monkeypatch.setenv("AUTH_ISSUER", "https://identity.example/")
    monkeypatch.setenv("AUTH_AUDIENCE", "ai-notebook-api")
    get_settings.cache_clear()
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["persistence_configured"] is True
    assert response.json()["checks"]["authentication_configured"] is False
    get_settings.cache_clear()


def test_metadata_does_not_claim_production_ready() -> None:
    response = client.get("/api/v1/meta")
    assert response.status_code == 200
    assert response.json()["production_ready"] is False


def test_readiness_requires_live_database_schema_and_jwks(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example:5432/app")
    monkeypatch.setenv("AUTH_JWKS_URL", "https://identity.example/.well-known/jwks.json")
    monkeypatch.setenv("AUTH_ISSUER", "https://identity.example/")
    monkeypatch.setenv("AUTH_AUDIENCE", "ai-notebook-api")
    monkeypatch.setattr(
        "ai_notebook_api.api.health._database_health",
        lambda _settings: (True, True),
    )
    monkeypatch.setattr(
        "ai_notebook_api.api.health.identity_provider_ready",
        lambda _settings: True,
    )
    get_settings.cache_clear()
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["database_reachable"] is True
    assert response.json()["checks"]["required_schema_present"] is True
    assert response.json()["checks"]["jwks_reachable"] is True
    assert response.json()["checks"]["production_database_tls_policy"] is True
    get_settings.cache_clear()


def test_readiness_fails_when_database_or_jwks_is_unavailable(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example:5432/app")
    monkeypatch.setenv("AUTH_JWKS_URL", "https://identity.example/.well-known/jwks.json")
    monkeypatch.setenv("AUTH_ISSUER", "https://identity.example/")
    monkeypatch.setenv("AUTH_AUDIENCE", "ai-notebook-api")
    monkeypatch.setattr(
        "ai_notebook_api.api.health._database_health",
        lambda _settings: (True, False),
    )
    monkeypatch.setattr(
        "ai_notebook_api.api.health.identity_provider_ready",
        lambda _settings: False,
    )
    get_settings.cache_clear()
    response = client.get("/health/ready")
    assert response.status_code == 503
    checks = response.json()["checks"]
    assert checks["required_schema_present"] is False
    assert checks["jwks_reachable"] is False
    get_settings.cache_clear()


def test_asyncpg_url_is_not_accepted_for_sync_sqlalchemy_sessions():
    assert Settings(database_url="postgresql+asyncpg://user:pass@db.example/app").persistence_configured is False


def test_database_tls_verification_requires_verify_full():
    assert Settings(
        database_url="postgresql://user:pass@db.example/app?sslmode=verify-full"
    ).database_tls_verified is True
    assert Settings(
        database_url="postgresql+psycopg://user:pass@db.example/app?sslmode=verify-full"
    ).database_tls_verified is True
    assert Settings(
        database_url="postgresql://user:pass@db.example/app?sslmode=require"
    ).database_tls_verified is False
    assert Settings(
        database_url="postgresql://user:pass@db.example/app?sslmode=verify-ca"
    ).database_tls_verified is False
    assert Settings(
        database_url="postgresql://user:pass@db.example/app"
    ).database_tls_verified is False


def test_production_readiness_fails_without_verified_database_tls(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example:5432/app?sslmode=require")
    monkeypatch.setenv("AUTH_JWKS_URL", "https://identity.example/.well-known/jwks.json")
    monkeypatch.setenv("AUTH_ISSUER", "https://identity.example/")
    monkeypatch.setenv("AUTH_AUDIENCE", "ai-notebook-api")
    monkeypatch.setattr(
        "ai_notebook_api.api.health._database_health",
        lambda _settings: (True, True),
    )
    monkeypatch.setattr(
        "ai_notebook_api.api.health.identity_provider_ready",
        lambda _settings: True,
    )
    get_settings.cache_clear()
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["production_database_tls_policy"] is False
    get_settings.cache_clear()


def test_production_readiness_accepts_verified_database_tls(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:pass@db.example:5432/app?sslmode=verify-full",
    )
    monkeypatch.setenv("AUTH_JWKS_URL", "https://identity.example/.well-known/jwks.json")
    monkeypatch.setenv("AUTH_ISSUER", "https://identity.example/")
    monkeypatch.setenv("AUTH_AUDIENCE", "ai-notebook-api")
    monkeypatch.setattr(
        "ai_notebook_api.api.health._database_health",
        lambda _settings: (True, True),
    )
    monkeypatch.setattr(
        "ai_notebook_api.api.health.identity_provider_ready",
        lambda _settings: True,
    )
    get_settings.cache_clear()
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["production_database_tls_policy"] is True
    get_settings.cache_clear()
