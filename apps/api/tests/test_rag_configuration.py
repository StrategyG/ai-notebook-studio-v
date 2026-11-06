import pytest

from ai_notebook_api.core.config import Settings, validate_rag_configuration


def _settings(**overrides) -> Settings:
    values = {
        "rag_enabled": True,
        "embedding_api_url": "https://embedding.example/v1/embeddings",
        "embedding_api_key": "test-secret",
        "embedding_model": "test-embedding-model",
        "embedding_dimensions": 1536,
    }
    values.update(overrides)
    return Settings(**values)


def test_embedding_configuration_accepts_a_valid_https_embeddings_endpoint() -> None:
    assert _settings().embedding_configured is True


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://embedding.example/v1/embeddings",
        "https://embedding.example/v1/chat/completions",
        "https://embedding.example/v1/embeddings?api_key=secret",
        "https://user:password@embedding.example/v1/embeddings",
        "https://embedding.example/v1/embeddings#fragment",
    ],
)
def test_embedding_configuration_rejects_unsafe_or_wrong_endpoint_urls(endpoint: str) -> None:
    assert _settings(embedding_api_url=endpoint).embedding_configured is False


def test_embedding_configuration_allows_local_http_only_outside_production() -> None:
    local = "http://127.0.0.1:8080/v1/embeddings"

    assert _settings(embedding_api_url=local).embedding_configured is True
    assert _settings(app_env="production", embedding_api_url=local).embedding_configured is False


def test_embedding_configuration_rejects_blank_secret_and_model() -> None:
    assert _settings(embedding_api_key=" ").embedding_configured is False
    assert _settings(embedding_model=" ").embedding_configured is False


def test_enabled_rag_fails_closed_when_embedding_endpoint_is_invalid() -> None:
    with pytest.raises(RuntimeError, match="embedding provider"):
        validate_rag_configuration(
            _settings(embedding_api_url="https://embedding.example/v1/chat/completions")
        )
