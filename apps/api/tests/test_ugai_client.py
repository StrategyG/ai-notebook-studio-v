from uuid import uuid4

import httpx
import pytest

from ai_notebook_api.services.ugai_client import (
    MAX_RESPONSE_BYTES,
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
async def test_submit_task_uses_encrypted_input_then_task_reference() -> None:
    captured = []
    task_id = uuid4()
    request_id = uuid4()
    tenant_id = uuid4()
    idempotency_key = uuid4()
    workspace_id = uuid4()
    input_ref = uuid4()

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/api/v1/task-inputs":
            return httpx.Response(
                201,
                json={
                    "input_ref": str(input_ref),
                    "input_digest": "a" * 64,
                    "project_id": "project-1",
                    "workspace_id": str(workspace_id),
                    "expires_at": "2026-12-05T00:00:00+00:00",
                },
            )
        if request.url.path == "/api/v1/tasks":
            return httpx.Response(
                202,
                json={
                    "task_id": str(task_id),
                    "request_id": request.headers["X-Request-ID"],
                    "state": "ACCEPTED",
                    "created_at": "2026-11-05T00:00:00+00:00",
                },
            )
        return httpx.Response(404)

    provider = TokenProvider()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = UGAITaskClient(
        base_url="https://ugai.example",
        audience="ugai-api",
        token_provider=provider,
        http_client=http,
    )
    submission = TaskSubmission(
        intent="Explain this notebook",
        workspace_id=workspace_id,
    )
    receipt = await client.submit_task(
        submission,
        project_id="project-1",
        subject="user-123",
        tenant_id=tenant_id,
        request_id=request_id,
        idempotency_key=idempotency_key,
    )

    assert isinstance(receipt, TaskReceipt)
    assert receipt.task_id == task_id
    assert receipt.request_id == request_id
    assert len(captured) == 2
    input_request, task_request = captured
    assert input_request.url.path == "/api/v1/task-inputs"
    assert task_request.url.path == "/api/v1/tasks"
    assert input_request.headers["Authorization"] == "Bearer service-token"
    assert task_request.headers["Authorization"] == "Bearer service-token"
    for request in captured:
        assert request.headers["Idempotency-Key"] == str(idempotency_key)
        assert request.headers["X-Request-ID"] == str(request_id)
        assert b"tenant_id" not in request.content
        assert b"subject" not in request.content

    input_payload = json.loads(input_request.content)
    task_payload = json.loads(task_request.content)
    assert input_payload["intent"] == "Explain this notebook"
    assert input_payload["project_id"] == "project-1"
    assert task_payload == {
        "project_id": "project-1",
        "input_ref": str(input_ref),
        "input_digest": "a" * 64,
        "task_type": "notebook_request",
        "max_retries": 2,
    }
    assert b"Explain this notebook" not in task_request.content
    assert len(provider.calls) == 2
    assert all(call["subject"] == "user-123" for call in provider.calls)
    assert all(call["tenant_id"] == tenant_id for call in provider.calls)
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
            project_id="project-1",
            subject="user-1",
            tenant_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )
    await http.aclose()


@pytest.mark.asyncio
async def test_submit_rejects_unknown_state_and_non_json_responses() -> None:
    task_id = uuid4()
    responses = [
        httpx.Response(
            202,
            json={
                "task_id": str(task_id),
                "request_id": str(uuid4()),
                "state": "MAGICALLY_DONE",
            },
        ),
        httpx.Response(202, text="accepted", headers={"content-type": "text/plain"}),
    ]
    for response in responses:
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request, response=response: response)
        )
        client = UGAITaskClient(
            base_url="https://ugai.example",
            audience="ugai-api",
            token_provider=TokenProvider(),
            http_client=http,
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
        "state": "ACCEPTED",
        "padding": "x" * MAX_RESPONSE_BYTES,
    }
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(202, json=payload))
    )
    client = UGAITaskClient(
        base_url="https://ugai.example",
        audience="ugai-api",
        token_provider=TokenProvider(),
        http_client=http,
    )
    with pytest.raises(UGAIUnavailable):
        await client.submit_task(
            TaskSubmission(intent="test", workspace_id=uuid4()),
            project_id="project-1",
            subject="user-1",
            tenant_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )
    await http.aclose()


@pytest.mark.asyncio
async def test_submit_rejects_duplicate_json_keys() -> None:
    task_id = uuid4()
    duplicate_json = (
        '{"task_id":"' + str(task_id) + '","request_id":"' + str(uuid4())
        + '","state":"ACCEPTED","state":"COMPLETED"}'
    )
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                202, content=duplicate_json, headers={"content-type": "application/json"}
            )
        )
    )
    client = UGAITaskClient(
        base_url="https://ugai.example",
        audience="ugai-api",
        token_provider=TokenProvider(),
        http_client=http,
    )
    with pytest.raises(UGAIUnavailable):
        await client.submit_task(
            TaskSubmission(intent="test", workspace_id=uuid4()),
            project_id="project-1",
            subject="user-1",
            tenant_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )
    await http.aclose()


@pytest.mark.asyncio
async def test_submit_rejects_receipt_with_wrong_request_id() -> None:
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                202,
                json={
                    "task_id": str(uuid4()),
                    "request_id": str(uuid4()),
                    "state": "ACCEPTED",
                },
            )
        )
    )
    client = UGAITaskClient(
        base_url="https://ugai.example",
        audience="ugai-api",
        token_provider=TokenProvider(),
        http_client=http,
    )
    with pytest.raises(UGAIUnavailable):
        await client.submit_task(
            TaskSubmission(intent="test", workspace_id=uuid4()),
            project_id="project-1",
            subject="user-1",
            tenant_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )
    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get", "cancel"])
async def test_task_status_rejects_response_for_different_task(operation: str) -> None:
    requested_task_id = uuid4()
    wrong_task_id = uuid4()
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "task_id": str(wrong_task_id),
                    "request_id": str(uuid4()),
                    "state": "RUNNING",
                },
            )
        )
    )
    client = UGAITaskClient(
        base_url="https://ugai.example",
        audience="ugai-api",
        token_provider=TokenProvider(),
        http_client=http,
    )

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
    await http.aclose()
