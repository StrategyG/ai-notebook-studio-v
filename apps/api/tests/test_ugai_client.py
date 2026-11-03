from uuid import uuid4

import httpx
import pytest

from ai_notebook_api.services.ugai_client import (
    TaskReceipt,
    TaskSubmission,
    UGAIAuthenticationError,
    UGAITaskClient,
    UGAIUnavailable,
)


class TokenProvider:
    def __init__(self, token: str = "service-token") -> None:
        self.token = token
        self.calls = []

    async def get_access_token(self, **kwargs):
        self.calls.append(kwargs)
        return self.token


@pytest.mark.asyncio
async def test_submit_task_binds_identity_to_token_and_idempotency() -> None:
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            202,
            json={
                "task_id": str(uuid4()),
                "request_id": request.headers["X-Request-ID"],
                "state": "ACCEPTED",
            },
        )

    provider = TokenProvider()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = UGAITaskClient(
        base_url="https://ugai.example",
        audience="ugai-api",
        token_provider=provider,
        http_client=http,
    )
    tenant_id, request_id, idempotency_key = uuid4(), uuid4(), uuid4()
    submission = TaskSubmission(intent="Explain this notebook", workspace_id=uuid4())
    receipt = await client.submit_task(
        submission,
        subject="user-123",
        tenant_id=tenant_id,
        request_id=request_id,
        idempotency_key=idempotency_key,
    )

    assert isinstance(receipt, TaskReceipt)
    request = captured["request"]
    assert request.headers["Authorization"] == "Bearer service-token"
    assert request.headers["Idempotency-Key"] == str(idempotency_key)
    assert request.headers["X-Request-ID"] == str(request_id)
    assert provider.calls[0]["subject"] == "user-123"
    assert provider.calls[0]["tenant_id"] == tenant_id
    assert b"tenant_id" not in request.content
    assert b"subject" not in request.content
    await http.aclose()


def test_client_rejects_non_https_endpoint() -> None:
    with pytest.raises(ValueError):
        UGAITaskClient(
            base_url="http://ugai.example",
            audience="ugai-api",
            token_provider=TokenProvider(),
        )


@pytest.mark.asyncio
async def test_client_fails_closed_when_token_provider_returns_empty_token() -> None:
    provider = TokenProvider(token="")
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    )
    client = UGAITaskClient(
        base_url="https://ugai.example",
        audience="ugai-api",
        token_provider=provider,
        http_client=http,
    )
    with pytest.raises(UGAIAuthenticationError):
        await client.get_task(
            uuid4(), subject="user-1", tenant_id=uuid4(), request_id=uuid4()
        )
    await http.aclose()


@pytest.mark.asyncio
async def test_submit_does_not_hide_uncertain_remote_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = UGAITaskClient(
        base_url="https://ugai.example",
        audience="ugai-api",
        token_provider=TokenProvider(),
        http_client=http,
    )
    with pytest.raises(UGAIUnavailable, match="reconcile by idempotency key"):
        await client.submit_task(
            TaskSubmission(intent="test", workspace_id=uuid4()),
            subject="user-1",
            tenant_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )
    await http.aclose()
