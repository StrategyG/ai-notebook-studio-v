from __future__ import annotations

import json
import math
from typing import Protocol

import httpx

from ai_notebook_api.core.config import Settings


class EmbeddingServiceError(RuntimeError):
    """The configured embedding service failed or returned an invalid vector."""


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one finite, fixed-dimension embedding for each input text."""


class OpenAICompatibleEmbeddingClient:
    """Real HTTP adapter for an OpenAI-compatible embeddings endpoint.

    No synthetic or fallback embeddings are generated. An unavailable or malformed
    provider response fails the ingestion/search request closed.
    """

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.settings.embedding_configured:
            raise EmbeddingServiceError("embedding provider is not configured")
        if any(not isinstance(item, str) or not item.strip() for item in texts):
            raise ValueError("embedding input must contain non-empty text")

        vectors: list[list[float]] = []
        batch_size = 32
        for offset in range(0, len(texts), batch_size):
            batch = texts[offset : offset + batch_size]
            vectors.extend(await self._embed_batch(batch))
        return vectors

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        payload = {
            "model": self.settings.embedding_model,
            "input": texts,
            "dimensions": self.settings.embedding_dimensions,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.embedding_api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(self.settings.embedding_timeout_seconds)
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                async with client.stream(
                    "POST",
                    self.settings.embedding_api_url,
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status_code < 200 or response.status_code >= 300:
                        raise EmbeddingServiceError(
                            f"embedding provider returned HTTP {response.status_code}"
                        )
                    body = bytearray()
                    async for part in response.aiter_bytes():
                        body.extend(part)
                        if len(body) > 8 * 1024 * 1024:
                            raise EmbeddingServiceError("embedding response exceeded the size limit")
        except httpx.TimeoutException as exc:
            raise EmbeddingServiceError("embedding provider timed out") from exc
        except httpx.HTTPError as exc:
            raise EmbeddingServiceError("embedding provider request failed") from exc

        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EmbeddingServiceError("embedding provider returned invalid JSON") from exc

        data = decoded.get("data") if isinstance(decoded, dict) else None
        if not isinstance(data, list) or len(data) != len(texts):
            raise EmbeddingServiceError("embedding provider returned an unexpected item count")

        indexed: list[tuple[int, list[float]]] = []
        seen: set[int] = set()
        for fallback_index, item in enumerate(data):
            if not isinstance(item, dict):
                raise EmbeddingServiceError("embedding provider returned an invalid item")
            index = item.get("index", fallback_index)
            embedding = item.get("embedding")
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or index < 0
                or index >= len(texts)
                or index in seen
            ):
                raise EmbeddingServiceError("embedding provider returned invalid item ordering")
            if not isinstance(embedding, list) or len(embedding) != self.settings.embedding_dimensions:
                raise EmbeddingServiceError("embedding provider returned an unexpected vector dimension")
            vector: list[float] = []
            for value in embedding:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise EmbeddingServiceError("embedding vector contains a non-numeric value")
                numeric = float(value)
                if not math.isfinite(numeric):
                    raise EmbeddingServiceError("embedding vector contains a non-finite value")
                vector.append(numeric)
            seen.add(index)
            indexed.append((index, vector))

        indexed.sort(key=lambda item: item[0])
        return [vector for _, vector in indexed]
