"""Fail-closed asynchronous client for the UGAI task API.

The end-user and tenant identity must be bound by the deployment's token issuer.
This client never accepts actor_id or tenant_id in task payloads.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlparse
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_RESPONSE_BYTES = 65_536
MAX_BEARER_TOKEN_LENGTH = 8_192


class WorkflowTaskState(StrEnum):
    """Canonical state values emitted by UGAI's durable workflow state machine."""

    RECEIVED = "received"
    OBSERVING = "observing"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    BLOCKED = "blocked"
    FAILED = "failed"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"


class TaskDisplayState(StrEnum):
    """Notebook-facing presentation states; never persisted as workflow states."""

    ACCEPTED = "ACCEPTED"
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    VALIDATION = "VALIDATION"
    APPROVAL = "APPROVAL"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


_DISPLAY_STATE = {
    WorkflowTaskState.RECEIVED: TaskDisplayState.ACCEPTED,
    WorkflowTaskState.OBSERVING: TaskDisplayState.PLANNED,
    WorkflowTaskState.PLANNING: TaskDisplayState.PLANNED,
    WorkflowTaskState.EXECUTING: TaskDisplayState.RUNNING,
    WorkflowTaskState.VERIFYING: TaskDisplayState.VALIDATION,
    WorkflowTaskState.AWAITING_APPROVAL: TaskDisplayState.APPROVAL,
    WorkflowTaskState.AWAITING_CLARIFICATION: TaskDisplayState.WAITING,
    WorkflowTaskState.BLOCKED: TaskDisplayState.BLOCKED,
    WorkflowTaskState.FAILED: TaskDisplayState.FAILED,
    WorkflowTaskState.SUCCEEDED: TaskDisplayState.COMPLETED,
    WorkflowTaskState.CANCELLED: TaskDisplayState.CANCELLED,
}


def display_task_state(state: WorkflowTaskState | str) -> TaskDisplayState:
    """Map a canonical UGAI state to a display-only Notebook state."""
    try:
        canonical = WorkflowTaskState(state)
    except (TypeError, ValueError) as exc:
        raise ValueError("Unknown UGAI workflow state") from exc
    return _DISPLAY_STATE[canonical]


class UGAIClientError(RuntimeError):
    """Base error for UGAI integration failures."""


class UGAIUnavailable(UGAIClientError):
    """UGAI could not be reached or returned an invalid response."""


class UGAIAuthenticationError(UGAIClientError):
    """The service token could not be obtained."""


class UGAITokenProvider(Protocol):
    async def get_access_token(
        self, *, audience: str, scopes: tuple[str, ...], subject: str, tenant_id: UUID, workspace_id: UUID
    ) -> str: ...


class ArtifactReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1, max_length=128)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    media_type: str = Field(min_length=1, max_length=128)


class TaskSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: str = Field(min_length=1, max_length=4000)
    workspace_id: UUID
    notebook_id: UUID | None = None
    cell_revision: str | None = Field(default=None, max_length=128)
    artifacts: tuple[ArtifactReference, ...] = Field(default=(), max_length=32)
    requested_capabilities: tuple[str, ...] = Field(default=(), max_length=32)


class TaskReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    request_id: UUID
    state: WorkflowTaskState
    created_at: str | None = None


class TaskStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    request_id: UUID
    state: WorkflowTaskState
    result_reference: str | None = Field(default=None, max_length=512)
    error_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_:-]{0,127}$")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON response contains a duplicate object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"JSON response contains a non-finite number: {value}")


async def _read_json_object(response: httpx.Response) -> dict[str, object]:
    """Read a bounded JSON response and reject redirects, HTML and oversized bodies."""
    response.raise_for_status()
    media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json" and not media_type.endswith("+json"):
        raise ValueError("UGAI response content type is not JSON")

    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as exc:
            raise ValueError("UGAI response has an invalid content length") from exc
        if declared_size < 0 or declared_size > MAX_RESPONSE_BYTES:
            raise ValueError("UGAI response exceeds the permitted size")

    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
            raise ValueError("UGAI response exceeds the permitted size")
        body.extend(chunk)

    payload = json.loads(
        bytes(body),
        object_pairs_hook=_unique_json_object,
        parse_constant=_reject_json_constant,
    )
    if not isinstance(payload, dict):
        raise ValueError("UGAI response must be a JSON object")
    return payload


class UGAITaskClient:
    """Calls UGAI with a short-lived identity-bound service token.

    The HTTP client may be injected for tests. POST requests are not retried:
    a lost response can mean that the remote task was accepted.
    Responses are size-limited and validated against the task state contract.
    """

    def __init__(
        self,
        *,
        base_url: str,
        audience: str,
        token_provider: UGAITokenProvider,
        timeout_seconds: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        try:
            parsed = urlparse(base_url)
            hostname = parsed.hostname
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("UGAI base URL must be a valid HTTPS origin") from exc
        if (
            parsed.scheme != "https"
            or not hostname
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("UGAI base URL must be an HTTPS origin")
        if not audience or len(audience) > 255 or any(ch.isspace() for ch in audience):
            raise ValueError("A bounded UGAI token audience is required")
        if not 0 < timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be between 0 and 60")
        self._base_url = base_url.rstrip("/")
        self._audience = audience
        self._tokens = token_provider
        self._timeout = timeout_seconds
        self._http = http_client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_http = http_client is None

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _headers(
        self,
        *,
        subject: str,
        tenant_id: UUID,
        workspace_id: UUID,
        request_id: UUID,
        scopes: tuple[str, ...],
        idempotency_key: UUID | None = None,
    ) -> dict[str, str]:
        if not subject or len(subject) > 255:
            raise UGAIAuthenticationError("A verified subject is required")
        if not isinstance(scopes, tuple) or scopes not in {
            ("ugai:tasks:write",), ("ugai:tasks:read",), ("ugai:tasks:cancel",)
        }:
            raise UGAIAuthenticationError("A valid least-privilege task scope is required")
        try:
            token = await self._tokens.get_access_token(
                audience=self._audience,
                scopes=scopes,
                subject=subject,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
        except Exception as exc:
            raise UGAIAuthenticationError("Could not obtain UGAI service token") from exc
        if (
            not isinstance(token, str)
            or not token
            or len(token) > MAX_BEARER_TOKEN_LENGTH
            or any(ord(ch) < 33 or ord(ch) == 127 for ch in token)
        ):
            raise UGAIAuthenticationError("Token provider returned an invalid token")
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Request-ID": str(request_id),
            "Accept": "application/json",
        }
        if idempotency_key is not None:
            headers["Idempotency-Key"] = str(idempotency_key)
        return headers

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        async with self._http.stream(
            method,
            f"{self._base_url}{path}",
            headers=headers,
            json=payload,
            timeout=self._timeout,
        ) as response:
            return await _read_json_object(response)

    async def submit_task(
        self,
        submission: TaskSubmission,
        *,
        subject: str,
        tenant_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> TaskReceipt:
        headers = await self._headers(
            subject=subject,
            tenant_id=tenant_id,
            workspace_id=submission.workspace_id,
            request_id=request_id,
            scopes=("ugai:tasks:write",),
            idempotency_key=idempotency_key,
        )
        try:
            body = await self._request_json(
                "POST", "/api/v1/tasks", headers=headers,
                payload=submission.model_dump(mode="json"),
            )
            receipt = TaskReceipt.model_validate(body)
            if receipt.request_id != request_id:
                raise ValueError("UGAI returned a receipt for a different request")
            return receipt
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            raise UGAIUnavailable(
                "UGAI task submission failed or returned an invalid receipt; "
                "reconcile by idempotency key"
            ) from exc

    async def get_task(
        self, task_id: UUID, *, subject: str, tenant_id: UUID, workspace_id: UUID, request_id: UUID
    ) -> TaskStatus:
        headers = await self._headers(
            subject=subject, tenant_id=tenant_id, workspace_id=workspace_id, request_id=request_id,
            scopes=("ugai:tasks:read",),
        )
        try:
            body = await self._request_json(
                "GET", f"/api/v1/tasks/{task_id}", headers=headers
            )
            status = TaskStatus.model_validate(body)
            if status.task_id != task_id:
                raise ValueError("UGAI returned a status for a different task")
            if status.request_id != request_id:
                raise ValueError("UGAI returned a status for a different request")
            return status
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            raise UGAIUnavailable("UGAI task status request failed") from exc

    async def cancel_task(
        self, task_id: UUID, *, subject: str, tenant_id: UUID, workspace_id: UUID, request_id: UUID
    ) -> TaskStatus:
        headers = await self._headers(
            subject=subject, tenant_id=tenant_id, workspace_id=workspace_id, request_id=request_id,
            scopes=("ugai:tasks:cancel",),
        )
        try:
            body = await self._request_json(
                "POST", f"/api/v1/tasks/{task_id}/cancel", headers=headers
            )
            status = TaskStatus.model_validate(body)
            if status.task_id != task_id:
                raise ValueError("UGAI returned a cancellation for a different task")
            if status.request_id != request_id:
                raise ValueError("UGAI returned a cancellation for a different request")
            return status
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            raise UGAIUnavailable("UGAI task cancellation request failed") from exc
