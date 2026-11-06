import json

import httpx
import pytest

from ai_notebook_api.core.config import Settings
from ai_notebook_api.rag.embeddings import EmbeddingServiceError, OpenAICompatibleEmbeddingClient

EMBEDDING_URL = "https://embedding.example/v1/embeddings"
DIMENSIONS = 1536


def embedding_settings() -> Settings:
    return Settings(
        rag_enabled=True,
        embedding_api_url=EMBEDDING_URL,
        embedding_api_key="test-secret",
        embedding_model="test-embedding-model",
        embedding_dimensions=DIMENSIONS,
    )


@pytest.mark.asyncio
async def test_embedding_client_calls_real_openai_compatible_contract_and_preserves_order() -> None:
    observed_batches: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-secret"
        payload = json.loads(request.content)
        observed_batches.append(len(payload["input"]))
        assert payload["model"] == "test-embedding-model"
        assert payload["dimensions"] == DIMENSIONS
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [float(index)] * DIMENSIONS}
                    for index in reversed(range(len(payload["input"])))
                ]
            },
        )

    client = OpenAICompatibleEmbeddingClient(
        embedding_settings(),
        transport=httpx.MockTransport(handler),
    )
    vectors = await client.embed([f"document {index}" for index in range(33)])

    assert observed_batches == [32, 1]
    assert len(vectors) == 33
    assert vectors[0][0] == 0.0
    assert vectors[31][0] == 31.0
    assert vectors[32][0] == 0.0


@pytest.mark.asyncio
async def test_embedding_client_rejects_provider_dimension_mismatch() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})

    client = OpenAICompatibleEmbeddingClient(
        embedding_settings(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(EmbeddingServiceError, match="dimension"):
        await client.embed(["one document"])


@pytest.mark.asyncio
async def test_embedding_client_rejects_non_finite_values() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        vector = [0.1] * DIMENSIONS
        vector[10] = float("nan")
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": vector}]})

    client = OpenAICompatibleEmbeddingClient(
        embedding_settings(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(EmbeddingServiceError, match="non-finite"):
        await client.embed(["one document"])


@pytest.mark.asyncio
async def test_embedding_client_does_not_echo_provider_error_body_or_secret() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="private provider diagnostics")

    client = OpenAICompatibleEmbeddingClient(
        embedding_settings(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(EmbeddingServiceError) as error:
        await client.embed(["one document"])

    assert "private provider diagnostics" not in str(error.value)
    assert "test-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_embedding_client_fails_closed_without_configuration() -> None:
    client = OpenAICompatibleEmbeddingClient(Settings())
    with pytest.raises(EmbeddingServiceError, match="not configured"):
        await client.embed(["one document"])
