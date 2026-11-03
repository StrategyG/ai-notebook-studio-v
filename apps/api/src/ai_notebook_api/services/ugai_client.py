"""Fail-closed asynchronous client for the UGAI task API.

The end-user and tenant identity must be bound by the deployment's token issuer.
This client never accepts actor_id or tenant_id in task payloads.
"""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlparse
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class UGAIClientError(RuntimeError):
    """Base error for UGAI integration failures."""


class UGAIUnavailable(UGAIClientError):
    """UGAI could not be reached or returned an invalid response."""


class UGAIAuthenticationError(UGAIClientError):
    """The service token could not be obtained."""


class UGAITokenProvider(Protocol):
    async def get_access_token(
        self, *, audience: str, scopes: tuple[str, ...], subject: str, tenant_id: UUID
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
    state: str
    created_at: str | None = None


class TaskStatus(BaseModel):
    model_config = ConfigDict(extra="allow")

    task_id: UUID
    request_id: UUID
    state: str
    result_reference: str | None = None
    error_code: str | None = None


class UGAITaskClient:
    """Calls UGAI with a short-lived identity-bound service token.

    The HTTP client may be injected for tests. POST requests are not retried:
    a lost response can mean that the remote task was accepted.
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
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("UGAI base URL must be an HTTPS origin")
        if not audience or len(audience) > 255:
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
        request_id: UUID,
        idempotency_key: UUID | None = None,
    ) -> dict[str, str]:
        if not subject or len(subject) > 255:
            raise UGAIAuthenticationError("A verified subject is required")
        try:
            token = await self._tokens.get_access_token(
                audience=self._audience,
                scopes=("ugai:tasks:write",),
                subject=subject,
                tenant_id=tenant_id,
            )
        except Exception as exc:
            raise UGAIAuthenticationError("Could not obtain UGAI service token") from exc
        if not token or any(ch.isspace() for ch in token):
            raise UGAIAuthenticationError("Token provider returned an invalid token")
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Request-ID": str(request_id),
            "Accept": "application/json",
        }
        if idempotency_key is not None:
            headers["Idempotency-Key"] = str(idempotency_key)
        return headers

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
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        try:
            response = await self._http.post(
                f"{self._base_url}/api/v1/tasks",
                headers=headers,
                json=submission.model_dump(mode="json"),
                timeout=self._timeout,
            )
            response.raise_for_status()
            return TaskReceipt.model_validate(response.json())
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            raise UGAIUnavailable(
                "UGAI task submission failed or returned an invalid receipt; reconcile by idempotency key"
            ) from exc

    async def get_task(
        self, task_id: UUID, *, subject: str, tenant_id: UUID, request_id: UUID
    ) -> TaskStatus:
        headers = await self._headers(
            subject=subject, tenant_id=tenant_id, request_id=request_id
        )
        try:
            response = await self._http.get(
                f"{self._base_url}/api/v1/tasks/{task_id}",
                headers=headers,
                timeout=self._timeout,
            )
            response.raise_for_status()
            return TaskStatus.model_validate(response.json())
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            raise UGAIUnavailable("UGAI task status request failed") from exc

    async def cancel_task(
        self, task_id: UUID, *, subject: str, tenant_id: UUID, request_id: UUID
    ) -> TaskStatus:
        headers = await self._headers(
            subject=subject, tenant_id=tenant_id, request_id=request_id
        )
        try:
            response = await self._http.post(
                f"{self._base_url}/api/v1/tasks/{task_id}/cancel",
                headers=headers,
                timeout=self._timeout,
            )
            response.raise_for_status()
            return TaskStatus.model_validate(response.json())
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            raise UGAIUnavailable("UGAI task cancellation request failed") from exc
