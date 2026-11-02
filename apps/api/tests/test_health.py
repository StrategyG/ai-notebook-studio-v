from fastapi.testclient import TestClient

from ai_notebook_api.core.config import get_settings
from ai_notebook_api.main import app

client = TestClient(app)


def test_liveness_is_available_without_external_services() -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_does_not_claim_ready_without_auth_and_database() -> None:
    get_settings.cache_clear()
    response = client.get("/health/ready")
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["checks"]["persistence_configured"] is False
    assert payload["checks"]["authentication_configured"] is False


def test_readiness_rejects_non_https_identity_endpoints(monkeypatch) -> None:
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
