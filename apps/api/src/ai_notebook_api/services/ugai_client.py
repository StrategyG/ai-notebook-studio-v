"""Fail-closed Notebook API client and OAuth token-exchange adapter for UGAI.

A Notebook user's verified access token is exchanged server-to-server for a
short-lived UGAI-audience token. User tokens, UGAI tokens and client secrets
never enter notebook task payloads, logs or browser responses.
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
TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"


class TaskStateCode(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    BLOCKED = "blocked"
    OUTCOME_UNKNOWN = "outcome_unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class UGAIClientError(RuntimeError):
    """Base error for safe, fail-closed UGAI integration failures."""


class UGAIUnavailable(UGAIClientError):
    """UGAI or the configured identity token exchange is unavailable."""


class UGAIAuthenticationError(UGAIClientError):
    """A scoped UGAI token could not be obtained or validated."""


class UGAITokenProvider(Protocol):
    async def get_access_token(
        self,
        *,
        audience: str,
        scopes: tuple[str, ...],
        subject: str,
        tenant_id: UUID,
        subject_token: str,
    ) -> str: ...

    async def aclose(self) -> None: ...


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON response contains a duplicate object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"JSON response contains a non-finite number: {value}")


def _json_object(response: httpx.Response, *, max_bytes: int = MAX_RESPONSE_BYTES) -> dict[str, object]:
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json" and not content_type.endswith("+json"):
        raise ValueError("Remote response content type is not JSON")
    if len(response.content) > max_bytes:
        raise ValueError("Remote JSON response exceeds the permitted size")
    declared = response.headers.get("content-length")
    if declared is not None:
        try:
            size = int(declared)
        except ValueError as exc:
            raise ValueError("Remote response content length is invalid") from exc
        if size < 0 or size > max_bytes:
            raise ValueError("Remote response exceeds the permitted size")
    payload = json.loads(
        response.content,
        object_pairs_hook=_unique_json_object,
        parse_constant=_reject_json_constant,
    )
    if not isinstance(payload, dict):
        raise ValueError("Remote JSON response must be an object")
    return payload


class OAuthTokenExchangeProvider:
    """RFC 8693 token exchange using a verified user's bearer token.

    The OAuth client authenticates only to the identity provider. The resulting
    access token must be minted for the requested UGAI audience and scopes;
    UGAI independently validates issuer, signature, audience, expiry and claims.
    """

    def __init__(
        self,
        *,
        token_endpoint: str,
        client_id: str,
        client_secret: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed = urlparse(token_endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("UGAI token exchange endpoint must be HTTPS")
        if not client_id or len(client_id) > 256:
            raise ValueError("UGAI OAuth client ID is invalid")
        if not client_secret or len(client_secret) > 4096:
            raise ValueError("UGAI OAuth client secret is invalid")
        self._endpoint = token_endpoint
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=3.0),
            trust_env=False,
            follow_redirects=False,
        )
        self._owns_http = http_client is None

    async def get_access_token(
        self,
        *,
        audience: str,
        scopes: tuple[str, ...],
        subject: str,
        tenant_id: UUID,
        subject_token: str,
    ) -> str:
        if not audience or len(audience) > 255 or any(ch.isspace() for ch in audience):
            raise UGAIAuthenticationError("UGAI token audience is invalid")
        if not subject or len(subject) > 255:
            raise UGAIAuthenticationError("Verified user subject is required")
        if not isinstance(tenant_id, UUID):
            raise UGAIAuthenticationError("Verified tenant identifier is required")
        if (
            not isinstance(subject_token, str)
            or not subject_token
            or len(subject_token) > MAX_BEARER_TOKEN_LENGTH
            or any(ord(ch) < 33 or ord(ch) == 127 for ch in subject_token)
        ):
            raise UGAIAuthenticationError("Verified subject token is invalid")
        if not scopes or any(
            not isinstance(scope, str)
            or not scope
            or len(scope) > 128
            or any(ch.isspace() for ch in scope)
            for scope in scopes
        ):
            raise UGAIAuthenticationError("UGAI token scopes are invalid")

        form = {
            "grant_type": TOKEN_EXCHANGE_GRANT,
            "subject_token_type": ACCESS_TOKEN_TYPE,
            "subject_token": subject_token,
            "audience": audience,
            "scope": " ".join(scopes),
        }
        try:
            async with self._http.stream(
                "POST",
                self._endpoint,
                data=form,
                auth=(self._client_id, self._client_secret),
                headers={"Accept": "application/json"},
            ) as response:
                response.raise_for_status()
                media_type = (
                    response.headers.get("content-type", "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                )
                if media_type != "application/json" and not media_type.endswith("+json"):
                    raise ValueError("Token exchange response is not JSON")
                declared = response.headers.get("content-length")
                if declared is not None:
                    try:
                        size = int(declared)
                    except ValueError as exc:
                        raise ValueError("Token exchange content length is invalid") from exc
                    if size < 0 or size > 16_384:
                        raise ValueError("Token exchange response exceeds size limit")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > 16_384:
                        raise ValueError("Token exchange response exceeds size limit")
                    body.extend(chunk)
                payload = json.loads(
                    bytes(body),
                    object_pairs_hook=_unique_json_object,
                    parse_constant=_reject_json_constant,
                )
                if not isinstance(payload, dict):
                    raise ValueError("Token exchange response must be an object")
        except (httpx.HTTPError, ValueError) as exc:
            raise UGAIAuthenticationError(
                "Identity provider token exchange failed"
            ) from exc

        token = payload.get("access_token")
        token_type = payload.get("token_type")
        expires_in = payload.get("expires_in")
        if (
            not isinstance(token, str)
            or not token
            or len(token) > MAX_BEARER_TOKEN_LENGTH
            or any(ord(ch) < 33 or ord(ch) == 127 for ch in token)
            or not isinstance(token_type, str)
            or token_type.lower() != "bearer"
            or isinstance(expires_in, bool)
            or not isinstance(expires_in, int)
            or not 1 <= expires_in <= 3600
        ):
            raise UGAIAuthenticationError(
                "Identity provider returned an invalid UGAI access token"
            )
        return token

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()


class ArtifactReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1, max_length=128)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    media_type: str = Field(min_length=1, max_length=128)


class TaskSubmission(BaseModel):
    """The exact UGAI v1 request contract; actor and tenant are never client fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    project_id: str = Field(min_length=1, max_length=128)
    workspace_id: UUID
    notebook_id: UUID | None = None
    cell_revision: str | None = Field(default=None, max_length=128)
    intent: str = Field(min_length=1, max_length=12_000)
    context: str = Field(default="", max_length=20_000)
    artifacts: tuple[ArtifactReference, ...] = Field(default=(), max_length=32)
    requested_capabilities: tuple[str, ...] = Field(default=(), max_length=32)


class TaskReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str
    task_id: UUID
    request_id: UUID
    correlation_id: UUID
    project_id: str
    state: TaskStateCode
    version: int
    retry_count: int
    retryable: bool
    error_code: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class TaskStatus(TaskReceipt):
    pass


class UGAITaskClient:
    """Bounded HTTPS client; POST is never automatically retried."""

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
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("UGAI base URL must be an HTTPS origin")
        if not audience or len(audience) > 255 or any(ch.isspace() for ch in audience):
            raise ValueError("UGAI audience is invalid")
        if not 0 < timeout_seconds <= 60:
            raise ValueError("UGAI HTTP timeout is invalid")
        self._base_url = base_url.rstrip("/")
        self._audience = audience
        self._tokens = token_provider
        self._timeout = timeout_seconds
        self._http = http_client or httpx.AsyncClient(
            timeout=timeout_seconds,
            trust_env=False,
            follow_redirects=False,
        )
        self._owns_http = http_client is None

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()
        await self._tokens.aclose()

    async def _headers(
        self,
        *,
        subject: str,
        tenant_id: UUID,
        subject_token: str,
        request_id: UUID,
        scopes: tuple[str, ...],
        idempotency_key: UUID | None = None,
        correlation_id: UUID | None = None,
    ) -> dict[str, str]:
        try:
            token = await self._tokens.get_access_token(
                audience=self._audience,
                scopes=scopes,
                subject=subject,
                tenant_id=tenant_id,
                subject_token=subject_token,
            )
        except UGAIClientError:
            raise
        except Exception as exc:
            raise UGAIAuthenticationError(
                "Could not obtain a UGAI access token"
            ) from exc
        if (
            not isinstance(token, str)
            or not token
            or len(token) > MAX_BEARER_TOKEN_LENGTH
            or any(ord(ch) < 33 or ord(ch) == 127 for ch in token)
        ):
            raise UGAIAuthenticationError("Token exchange returned an invalid bearer token")
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Request-ID": str(request_id),
            "Accept": "application/json",
        }
        if idempotency_key is not None:
            headers["Idempotency-Key"] = str(idempotency_key)
        if correlation_id is not None:
            headers["X-Correlation-ID"] = str(correlation_id)
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
            # Bound the body while streaming, not only after unbounded buffering.
            response.raise_for_status()
            media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media != "application/json" and not media.endswith("+json"):
                raise ValueError("UGAI response content type is not JSON")
            declared = response.headers.get("content-length")
            if declared is not None:
                try:
                    size = int(declared)
                except ValueError as exc:
                    raise ValueError("UGAI content length is invalid") from exc
                if size < 0 or size > MAX_RESPONSE_BYTES:
                    raise ValueError("UGAI response exceeds size limit")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise ValueError("UGAI response exceeds size limit")
                body.extend(chunk)
            value = json.loads(
                bytes(body),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
            if not isinstance(value, dict):
                raise ValueError("UGAI response must be a JSON object")
            return value

    async def submit_task(
        self,
        submission: TaskSubmission,
        *,
        subject: str,
        tenant_id: UUID,
        subject_token: str,
        request_id: UUID,
        idempotency_key: UUID,
        correlation_id: UUID | None = None,
    ) -> TaskReceipt:
        headers = await self._headers(
            subject=subject,
            tenant_id=tenant_id,
            subject_token=subject_token,
            request_id=request_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            scopes=("ugai:tasks:write",),
        )
        try:
            body = await self._request_json(
                "POST",
                "/api/v1/tasks",
                headers=headers,
                payload=submission.model_dump(mode="json"),
            )
            receipt = TaskReceipt.model_validate(body)
            if receipt.request_id != request_id or receipt.project_id != submission.project_id:
                raise ValueError("UGAI returned a receipt for a different request or project")
            return receipt
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            raise UGAIUnavailable(
                "UGAI task submission failed or returned an invalid receipt; reconcile by idempotency key"
            ) from exc

    async def get_task(
        self,
        task_id: UUID,
        *,
        subject: str,
        tenant_id: UUID,
        subject_token: str,
        request_id: UUID,
    ) -> TaskStatus:
        headers = await self._headers(
            subject=subject,
            tenant_id=tenant_id,
            subject_token=subject_token,
            request_id=request_id,
            scopes=("ugai:tasks:read",),
        )
        try:
            body = await self._request_json("GET", f"/api/v1/tasks/{task_id}", headers=headers)
            status = TaskStatus.model_validate(body)
            if status.task_id != task_id:
                raise ValueError("UGAI returned a status for a different task")
            return status
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            raise UGAIUnavailable("UGAI task status request failed") from exc

    async def cancel_task(
        self,
        task_id: UUID,
        *,
        subject: str,
        tenant_id: UUID,
        subject_token: str,
        request_id: UUID,
    ) -> TaskStatus:
        headers = await self._headers(
            subject=subject,
            tenant_id=tenant_id,
            subject_token=subject_token,
            request_id=request_id,
            scopes=("ugai:tasks:cancel",),
        )
        try:
            body = await self._request_json(
                "POST", f"/api/v1/tasks/{task_id}/cancel", headers=headers
            )
            status = TaskStatus.model_validate(body)
            if status.task_id != task_id:
                raise ValueError("UGAI returned a cancellation for a different task")
            return status
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            raise UGAIUnavailable("UGAI task cancellation request failed") from exc
