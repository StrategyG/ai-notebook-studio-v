from __future__ import annotations

import base64
import json
from uuid import uuid4

import httpx
import pytest

from ai_notebook_api.services.ugai_client import (
    OAuthTokenExchangeProvider,
    TaskStateCode,
    TaskSubmission,
    UGAIAuthenticationError,
    UGAITaskClient,
    UGAIUnavailable,
)


class StaticTokenProvider:
    def __init__(self, token: str = "short-lived-ugai-token") -> None:
        self.token = token
        self.calls: list[dict[str, object]] = []

    async def get_access_token(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return self.token

    async def aclose(self) -> None:
        return None


def receipt(task_id, request_id, correlation_id, project_id="project-1", state="queued"):
    return {
        "contract_version": "1.0.0",
        "task_id": str(task_id),
        "request_id": str(request_id),
        "correlation_id": str(correlation_id),
        "project_id": project_id,
        "state": state,
        "version": 0,
        "retry_count": 0,
        "retryable": False,
        "error_code": None,
        "created_at": "2026-11-05T00:00:00+00:00",
        "updated_at": "2026-11-05T00:00:00+00:00",
    }


def submission():
    return TaskSubmission(
        project_id="project-1",
        intent="Explain why this notebook cell failed",
        context="The failure occurred after a database timeout.",
        workspace_id=uuid4(),
        notebook_id=uuid4(),
        cell_revision="cell-rev-42",
        requested_capabilities=("reasoning:read",),
    )


@pytest.mark.asyncio
async def test_token_exchange_uses_rfc8693_and_never_returns_user_token():
    user_token = "user-access-token-never-forwarded"
    client_secret = "oauth-client-secret-never-logged"
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["form"] = dict(
            item.split("=", 1)
            for item in request.content.decode().split("&")
        )
        return httpx.Response(
            200,
            json={
                "access_token": "minted-ugai-token",
                "token_type": "Bearer",
                "expires_in": 300,
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OAuthTokenExchangeProvider(
        token_endpoint="https://identity.example.test/oauth/token",
        client_id="notebook-api",
        client_secret=client_secret,
        http_client=http,
    )
    result = await provider.get_access_token(
        audience="ugai-api",
        scopes=("ugai:tasks:write",),
        subject="user-subject-1",
        tenant_id=uuid4(),
        subject_token=user_token,
    )

    assert result == "minted-ugai-token"
    expected_basic = base64.b64encode(
        f"notebook-api:{client_secret}".encode()
    ).decode()
    assert seen["auth"] == f"Basic {expected_basic}"
    assert seen["form"]["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"
    assert seen["form"]["subject_token"] == user_token
    assert seen["form"]["audience"] == "ugai-api"
    assert seen["form"]["scope"] == "ugai:tasks:write"
    assert user_token not in result
    await http.aclose()


@pytest.mark.asyncio
async def test_notebook_client_posts_exact_ugai_contract_once_without_identity_fields():
    task_id, request_id, correlation_id = uuid4(), uuid4(), uuid4()
    captured = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            202,
            json=receipt(task_id, request_id, correlation_id),
        )

    provider = StaticTokenProvider()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = UGAITaskClient(
        base_url="https://ugai.example.test",
        audience="ugai-api",
        token_provider=provider,
        http_client=http,
    )
    request = submission()
    result = await client.submit_task(
        request,
        subject="issuer-scoped-user",
        tenant_id=uuid4(),
        subject_token="verified-user-token",
        request_id=request_id,
        idempotency_key=uuid4(),
        correlation_id=correlation_id,
    )

    assert result.task_id == task_id
    assert result.state is TaskStateCode.QUEUED
    assert len(captured) == 1
    outgoing = captured[0]
    assert outgoing.method == "POST"
    assert outgoing.url.path == "/api/v1/tasks"
    assert outgoing.headers["Authorization"] == "Bearer short-lived-ugai-token"
    body = json.loads(outgoing.content)
    assert body["project_id"] == "project-1"
    assert body["intent"] == request.intent
    assert body["context"] == request.context
    assert body["workspace_id"] == str(request.workspace_id)
    assert "tenant_id" not in body
    assert "subject" not in body
    assert "actor_id" not in body
    assert provider.calls[0]["scopes"] == ("ugai:tasks:write",)
    assert provider.calls[0]["subject_token"] == "verified-user-token"
    await http.aclose()


@pytest.mark.asyncio
async def test_task_status_and_cancel_use_canonical_state_vocabulary_and_scopes():
    task_id, request_id, correlation_id = uuid4(), uuid4(), uuid4()
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(
            200,
            json=receipt(
                task_id,
                request_id,
                correlation_id,
                state="awaiting_approval" if request.method == "GET" else "cancelled",
            ),
        )

    provider = StaticTokenProvider()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = UGAITaskClient(
        base_url="https://ugai.example.test",
        audience="ugai-api",
        token_provider=provider,
        http_client=http,
    )
    status = await client.get_task(
        task_id,
        subject="user-1",
        tenant_id=uuid4(),
        subject_token="user-token",
        request_id=request_id,
    )
    cancelled = await client.cancel_task(
        task_id,
        subject="user-1",
        tenant_id=uuid4(),
        subject_token="user-token",
        request_id=request_id,
    )

    assert status.state is TaskStateCode.AWAITING_APPROVAL
    assert cancelled.state is TaskStateCode.CANCELLED
    assert seen == [
        ("GET", f"/api/v1/tasks/{task_id}"),
        ("POST", f"/api/v1/tasks/{task_id}/cancel"),
    ]
    assert provider.calls[0]["scopes"] == ("ugai:tasks:read",)
    assert provider.calls[1]["scopes"] == ("ugai:tasks:cancel",)
    await http.aclose()


@pytest.mark.asyncio
async def test_client_rejects_unknown_state_and_wrong_task_id():
    task_id, request_id, correlation_id = uuid4(), uuid4(), uuid4()
    invalid = receipt(uuid4(), request_id, correlation_id, state="magically_done")

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=invalid)
        )
    )
    client = UGAITaskClient(
        base_url="https://ugai.example.test",
        audience="ugai-api",
        token_provider=StaticTokenProvider(),
        http_client=http,
    )
    with pytest.raises(UGAIUnavailable):
        await client.get_task(
            task_id,
            subject="user-1",
            tenant_id=uuid4(),
            subject_token="user-token",
            request_id=request_id,
        )
    await http.aclose()


@pytest.mark.asyncio
async def test_token_exchange_fails_closed_on_non_bearer_or_unbounded_expiry():
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "access_token": "token",
                    "token_type": "MAC",
                    "expires_in": 999999,
                },
            )
        )
    )
    provider = OAuthTokenExchangeProvider(
        token_endpoint="https://identity.example.test/oauth/token",
        client_id="client",
        client_secret="secret",
        http_client=http,
    )
    with pytest.raises(UGAIAuthenticationError):
        await provider.get_access_token(
            audience="ugai",
            scopes=("ugai:tasks:write",),
            subject="user-1",
            tenant_id=uuid4(),
            subject_token="user-token",
        )
    await http.aclose()
