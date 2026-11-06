from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from ai_notebook_api.api.tasks import (
    _map_ugai_error,
    _user_token,
    get_ugai_task_client,
    require_agents_run,
    require_notebooks_read,
)
from ai_notebook_api.db.models import TenantMembership
from ai_notebook_api.main import app
from ai_notebook_api.security.auth import Principal, bearer_scheme, get_current_principal
from ai_notebook_api.services.ugai_client import (
    TaskReceipt,
    TaskStateCode,
    TaskStatus,
    UGAIAuthenticationError,
    UGAIUnavailable,
)


class FakeUGAITaskClient:
    def __init__(self):
        self.calls = []

    async def submit_task(self, submission, **kwargs):
        self.calls.append(("submit", submission, kwargs))
        return TaskReceipt(
            contract_version="1.0.0",
            task_id=UUID("a3c605dc-14c1-4649-9bfb-cc1dcd1a73b1"),
            request_id=kwargs["request_id"],
            correlation_id=kwargs.get("correlation_id") or kwargs["request_id"],
            project_id=submission.project_id,
            state=TaskStateCode.QUEUED,
            version=0,
            retry_count=0,
            retryable=False,
            error_code=None,
            created_at="2026-11-05T00:00:00+00:00",
            updated_at="2026-11-05T00:00:00+00:00",
        )

    async def get_task(self, task_id, **kwargs):
        self.calls.append(("get", task_id, kwargs))
        return TaskStatus(
            contract_version="1.0.0",
            task_id=task_id,
            request_id=kwargs["request_id"],
            correlation_id=kwargs["request_id"],
            project_id="project-1",
            state=TaskStateCode.AWAITING_APPROVAL,
            version=2,
            retry_count=0,
            retryable=False,
            error_code=None,
            created_at="2026-11-05T00:00:00+00:00",
            updated_at="2026-11-05T00:00:00+00:00",
        )

    async def cancel_task(self, task_id, **kwargs):
        self.calls.append(("cancel", task_id, kwargs))
        return TaskStatus(
            contract_version="1.0.0",
            task_id=task_id,
            request_id=kwargs["request_id"],
            correlation_id=kwargs["request_id"],
            project_id="project-1",
            state=TaskStateCode.CANCELLED,
            version=3,
            retry_count=0,
            retryable=False,
            error_code=None,
            created_at="2026-11-05T00:00:00+00:00",
            updated_at="2026-11-05T00:00:00+00:00",
        )


@pytest.fixture
def notebook_api():
    tenant_id = uuid4()
    subject = "issuer-scoped-user"
    principal = Principal(
        issuer="https://identity.example/",
        subject=subject,
        tenant_id=tenant_id,
        roles=frozenset(),
        scopes=frozenset(),
    )
    membership = TenantMembership(
        tenant_id=tenant_id,
        subject=subject,
        role="owner",
        status="active",
    )
    client = FakeUGAITaskClient()

    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[bearer_scheme] = lambda: HTTPAuthorizationCredentials(
        scheme="Bearer", credentials="verified-user-token"
    )
    app.dependency_overrides[require_agents_run] = lambda: membership
    app.dependency_overrides[require_notebooks_read] = lambda: membership
    app.dependency_overrides[get_ugai_task_client] = lambda: client
    try:
        with TestClient(app) as test_client:
            yield test_client, client, tenant_id
    finally:
        app.dependency_overrides.clear()


def request_body():
    return {
        "project_id": "project-1",
        "workspace_id": str(uuid4()),
        "notebook_id": str(uuid4()),
        "cell_revision": "cell-17",
        "intent": "Explain this notebook failure",
        "context": "Database timeout after a long-running cell.",
        "artifacts": [],
        "requested_capabilities": ["reasoning:read"],
    }


def test_submit_route_checks_active_membership_and_passes_user_token_only_server_side(notebook_api):
    client, ugai, tenant_id = notebook_api
    request_id, correlation_id, idempotency_key = uuid4(), uuid4(), uuid4()
    response = client.post(
        "/api/v1/tasks",
        headers={
            "Idempotency-Key": str(idempotency_key),
            "X-Request-ID": str(request_id),
            "X-Correlation-ID": str(correlation_id),
            "Authorization": "Bearer verified-user-token",
        },
        json=request_body(),
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["state"] == "queued"
    assert body["contract_version"] == "1.0.0"
    assert body["request_id"] == str(request_id)

    kind, submission, kwargs = ugai.calls[0]
    assert kind == "submit"
    assert submission.project_id == "project-1"
    assert kwargs["subject"] == "issuer-scoped-user"
    assert kwargs["tenant_id"] == tenant_id
    assert kwargs["subject_token"] == "verified-user-token"
    assert kwargs["request_id"] == request_id
    assert kwargs["correlation_id"] == correlation_id
    assert kwargs["idempotency_key"] == idempotency_key
    assert "verified-user-token" not in str(body)


def test_read_and_cancel_routes_use_separate_authorized_ugai_operations(notebook_api):
    client, ugai, _tenant_id = notebook_api
    task_id = UUID("a3c605dc-14c1-4649-9bfb-cc1dcd1a73b1")

    read = client.get(
        f"/api/v1/tasks/{task_id}",
        headers={"Authorization": "Bearer verified-user-token"},
    )
    cancel = client.post(
        f"/api/v1/tasks/{task_id}/cancel",
        headers={"Authorization": "Bearer verified-user-token"},
    )

    assert read.status_code == 200
    assert read.json()["state"] == "awaiting_approval"
    assert cancel.status_code == 200
    assert cancel.json()["state"] == "cancelled"
    assert [call[0] for call in ugai.calls] == ["get", "cancel"]


def test_missing_ugai_client_fails_closed(notebook_api):
    _client, _ugai, _tenant_id = notebook_api
    from ai_notebook_api.api.tasks import router

    isolated = FastAPI()
    isolated.include_router(router)
    isolated.dependency_overrides[get_current_principal] = app.dependency_overrides[get_current_principal]
    isolated.dependency_overrides[bearer_scheme] = app.dependency_overrides[bearer_scheme]
    isolated.dependency_overrides[require_agents_run] = app.dependency_overrides[require_agents_run]
    with TestClient(isolated) as isolated_client:
        response = isolated_client.post(
            "/api/v1/tasks",
            headers={"Idempotency-Key": str(uuid4())},
            json=request_body(),
        )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "ugai_integration_unavailable"


def test_membership_tenant_mismatch_is_rejected(notebook_api):
    client, ugai, tenant_id = notebook_api
    from ai_notebook_api.api.tasks import require_agents_run
    foreign = TenantMembership(
        tenant_id=uuid4(),
        subject="issuer-scoped-user",
        role="owner",
        status="active",
    )
    app.dependency_overrides[require_agents_run] = lambda: foreign
    response = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": str(uuid4())},
        json=request_body(),
    )
    assert response.status_code == 403
    assert ugai.calls == []


def test_task_routes_map_ugai_authentication_and_availability_errors(notebook_api):
    client, ugai, _tenant_id = notebook_api

    async def authentication_failure(*_args, **_kwargs):
        raise UGAIAuthenticationError("private provider details")

    async def availability_failure(*_args, **_kwargs):
        raise UGAIUnavailable("private provider diagnostics")

    ugai.submit_task = authentication_failure
    response = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": str(uuid4())},
        json=request_body(),
    )
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "ugai_identity_exchange_failed"
    assert "private provider details" not in response.text

    ugai.get_task = availability_failure
    task_id = UUID("a3c605dc-14c1-4649-9bfb-cc1dcd1a73b1")
    response = client.get(f"/api/v1/tasks/{task_id}")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "ugai_task_service_unavailable"
    assert "private provider diagnostics" not in response.text


def test_cancel_route_maps_ugai_unavailable_error(notebook_api):
    client, ugai, _tenant_id = notebook_api

    async def availability_failure(*_args, **_kwargs):
        raise UGAIUnavailable("private cancellation diagnostics")

    ugai.cancel_task = availability_failure
    task_id = UUID("a3c605dc-14c1-4649-9bfb-cc1dcd1a73b1")
    response = client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "ugai_task_service_unavailable"
    assert "private cancellation diagnostics" not in response.text


def test_task_routes_reject_missing_bearer_credentials(notebook_api):
    client, ugai, _tenant_id = notebook_api
    app.dependency_overrides[bearer_scheme] = lambda: None
    response = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": str(uuid4())},
        json=request_body(),
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert ugai.calls == []


def test_task_helpers_return_sanitized_http_errors_and_require_bearer():
    with pytest.raises(HTTPException) as missing:
        _user_token(None)
    assert missing.value.status_code == 401
    assert _map_ugai_error(UGAIAuthenticationError("sensitive")).status_code == 502
    assert _map_ugai_error(UGAIUnavailable("sensitive")).status_code == 503
    assert _map_ugai_error(RuntimeError("sensitive")).detail == {
        "code": "ugai_task_service_unavailable"
    }
