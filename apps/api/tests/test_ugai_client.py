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
    TaskDisplayState,
    WorkflowTaskState,
    display_task_state,
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
                "state": "received",
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
        "state": "received",
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
                    "state": "received",
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
                    "state": "executing",
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

@pytest.mark.parametrize(
    ("workflow_state", "display_state"),
    [
        (WorkflowTaskState.RECEIVED, TaskDisplayState.ACCEPTED),
        (WorkflowTaskState.OBSERVING, TaskDisplayState.PLANNED),
        (WorkflowTaskState.PLANNING, TaskDisplayState.PLANNED),
        (WorkflowTaskState.EXECUTING, TaskDisplayState.RUNNING),
        (WorkflowTaskState.VERIFYING, TaskDisplayState.VALIDATION),
        (WorkflowTaskState.AWAITING_APPROVAL, TaskDisplayState.APPROVAL),
        (WorkflowTaskState.AWAITING_CLARIFICATION, TaskDisplayState.WAITING),
        (WorkflowTaskState.BLOCKED, TaskDisplayState.BLOCKED),
        (WorkflowTaskState.FAILED, TaskDisplayState.FAILED),
        (WorkflowTaskState.SUCCEEDED, TaskDisplayState.COMPLETED),
        (WorkflowTaskState.CANCELLED, TaskDisplayState.CANCELLED),
    ],
)
def test_canonical_ugai_state_maps_to_notebook_display_state(
    workflow_state: WorkflowTaskState, display_state: TaskDisplayState
) -> None:
    assert display_task_state(workflow_state) is display_state
    assert WorkflowTaskState(workflow_state.value) is workflow_state


def test_display_state_rejects_noncanonical_backend_values() -> None:
    with pytest.raises(ValueError, match="Unknown UGAI workflow state"):
        display_task_state("MAGICALLY_DONE")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get", "cancel"])
async def test_task_status_rejects_response_with_different_request_id(operation: str) -> None:
    task_id = uuid4()
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "task_id": str(task_id),
                    "request_id": str(uuid4()),
                    "state": "executing",
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
    request_id = uuid4()

    with pytest.raises(UGAIUnavailable):
        if operation == "get":
            await client.get_task(
                task_id, subject="user-1", tenant_id=uuid4(), request_id=request_id
            )
        else:
            await client.cancel_task(
                task_id, subject="user-1", tenant_id=uuid4(), request_id=request_id
            )
    await http.aclose()

