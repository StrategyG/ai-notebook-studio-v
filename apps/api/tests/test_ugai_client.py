import json
from uuid import uuid4

import httpx
import pytest

from ai_notebook_api.services.ugai_client import (
    MAX_RESPONSE_BYTES,
    TaskReceipt,
    TaskStateCode,
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


def make_client(handler, provider=None):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = UGAITaskClient(
        base_url="https://ugai.example",
        audience="ugai-api",
        token_provider=provider or TokenProvider(),
        http_client=http,
    )
    return client, http


@pytest.mark.asyncio
async def test_submit_task_uses_single_authenticated_idempotent_request() -> None:
    captured = []
    task_id, request_id = uuid4(), uuid4()
    tenant_id, workspace_id, idempotency_key = uuid4(), uuid4(), uuid4()

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            202,
            json={
                "task_id": str(task_id),
                "request_id": request.headers["X-Request-ID"],
                "state": "received",
                "created_at": "2026-11-05T00:00:00+00:00",
            },
        )

    provider = TokenProvider()
    client, http = make_client(handler, provider)
    submission = TaskSubmission(
        intent="Explain this notebook cell",
        context="The failure is reproducible.",
        workspace_id=workspace_id,
    )
    receipt = await client.submit_task(
        submission,
        subject="issuer-scoped-user",
        tenant_id=tenant_id,
        request_id=request_id,
        idempotency_key=idempotency_key,
    )

    assert isinstance(receipt, TaskReceipt)
    assert receipt.task_id == task_id
    assert receipt.request_id == request_id
    assert receipt.state is TaskStateCode.RECEIVED
    assert len(captured) == 1
    request = captured[0]
    assert request.url.path == "/api/v1/tasks"
    assert request.headers["Authorization"] == "Bearer service-token"
    assert request.headers["Idempotency-Key"] == str(idempotency_key)
    assert request.headers["X-Request-ID"] == str(request_id)
    body = json.loads(request.content)
    assert body["intent"] == "Explain this notebook cell"
    assert body["context"] == "The failure is reproducible."
    assert body["workspace_id"] == str(workspace_id)
    assert "tenant_id" not in body
    assert "subject" not in body
    assert "actor_id" not in body
    assert provider.calls == [{
        "audience": "ugai-api",
        "scopes": ("ugai:tasks:write",),
        "subject": "issuer-scoped-user",
        "tenant_id": tenant_id,
    }]
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
    client, http = make_client(
        lambda request: httpx.Response(500),
        provider,
    )
    with pytest.raises(UGAIAuthenticationError):
        await client.get_task(
            uuid4(), subject="user-1", tenant_id=uuid4(), request_id=uuid4()
        )
    await http.aclose()


@pytest.mark.asyncio
async def test_submit_does_not_hide_uncertain_remote_failure() -> None:
    client, http = make_client(lambda request: httpx.Response(503))
    with pytest.raises(UGAIUnavailable, match="reconcile by idempotency key"):
        await client.submit_task(
            TaskSubmission(intent="test", workspace_id=uuid4()),
            subject="user-1",
            tenant_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )
    await http.aclose()


@pytest.mark.asyncio
async def test_submit_rejects_unknown_state_and_non_json_responses() -> None:
    invalid_state = httpx.Response(
        202,
        json={
            "task_id": str(uuid4()),
            "request_id": str(uuid4()),
            "state": "MAGICALLY_DONE",
            "created_at": "2026-11-05T00:00:00+00:00",
        },
    )
    non_json = httpx.Response(
        202, text="accepted", headers={"content-type": "text/plain"}
    )
    for response in (invalid_state, non_json):
        client, http = make_client(
            lambda request, response=response: response
        )
        with pytest.raises(UGAIUnavailable):
            await client.submit_task(
                TaskSubmission(intent="test", workspace_id=uuid4()),
                subject="user-1",
                tenant_id=uuid4(),
                request_id=uuid4(),
                idempotency_key=uuid4(),
            )
        await http.aclose()


@pytest.mark.asyncio
async def test_submit_rejects_oversized_response() -> None:
    payload = {
        "task_id": str(uuid4()),
        "request_id": str(uuid4()),
        "state": "received",
        "created_at": "2026-11-05T00:00:00+00:00",
        "padding": "x" * MAX_RESPONSE_BYTES,
    }
    client, http = make_client(
        lambda request: httpx.Response(202, json=payload)
    )
    with pytest.raises(UGAIUnavailable):
        await client.submit_task(
            TaskSubmission(intent="test", workspace_id=uuid4()),
            subject="user-1",
            tenant_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )
    await http.aclose()


@pytest.mark.asyncio
async def test_submit_rejects_duplicate_json_keys() -> None:
    task_id, request_id = uuid4(), uuid4()
    duplicate_json = (
        '{"task_id":"' + str(task_id) + '","request_id":"' + str(request_id)
        + '","state":"received","state":"succeeded",'
        + '"created_at":"2026-11-05T00:00:00+00:00"}'
    )
    client, http = make_client(
        lambda request: httpx.Response(
            202,
            content=duplicate_json,
            headers={"content-type": "application/json"},
        )
    )
    with pytest.raises(UGAIUnavailable):
        await client.submit_task(
            TaskSubmission(intent="test", workspace_id=uuid4()),
            subject="user-1",
            tenant_id=uuid4(),
            request_id=request_id,
            idempotency_key=uuid4(),
        )
    await http.aclose()


@pytest.mark.asyncio
async def test_submit_rejects_receipt_with_wrong_request_id() -> None:
    client, http = make_client(
        lambda request: httpx.Response(
            202,
            json={
                "task_id": str(uuid4()),
                "request_id": str(uuid4()),
                "state": "received",
                "created_at": "2026-11-05T00:00:00+00:00",
            },
        )
    )
    with pytest.raises(UGAIUnavailable):
        await client.submit_task(
            TaskSubmission(intent="test", workspace_id=uuid4()),
            subject="user-1",
            tenant_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )
    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get", "cancel"])
async def test_task_status_rejects_response_for_different_task(operation: str) -> None:
    requested_task_id, wrong_task_id = uuid4(), uuid4()
    provider = TokenProvider()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "task_id": str(wrong_task_id),
                "request_id": request.headers["X-Request-ID"],
                "state": "received",
                "result_reference": None,
                "error_code": None,
            },
        )

    client, http = make_client(handler, provider)
    with pytest.raises(UGAIUnavailable):
        if operation == "get":
            await client.get_task(
                requested_task_id,
                subject="user-1",
                tenant_id=uuid4(),
                request_id=uuid4(),
            )
        else:
            await client.cancel_task(
                requested_task_id,
                subject="user-1",
                tenant_id=uuid4(),
                request_id=uuid4(),
            )
    if operation == "cancel":
        assert provider.calls[0]["scopes"] == ("ugai:tasks:cancel",)
    await http.aclose()
