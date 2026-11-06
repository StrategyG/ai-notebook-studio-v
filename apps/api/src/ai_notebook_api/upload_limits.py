from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ai_notebook_api.rag.document_loader import MAX_UPLOAD_BYTES

UPLOAD_ROUTE = "/api/v1/rag/documents/upload"
UPLOAD_REQUEST_OVERHEAD_BYTES = 64 * 1024
DEFAULT_UPLOAD_REQUEST_LIMIT = MAX_UPLOAD_BYTES + UPLOAD_REQUEST_OVERHEAD_BYTES


class UploadBodyLimitMiddleware:
    """Enforce a streaming request-body ceiling before multipart parsing can spool files."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_bytes: int = DEFAULT_UPLOAD_REQUEST_LIMIT,
    ) -> None:
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
            raise ValueError("max_bytes must be a positive integer")
        self.app = app
        self.max_bytes = max_bytes

    async def _reject(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        status_code: int,
        code: str,
    ) -> None:
        body = json.dumps({"detail": {"code": code, "max_request_bytes": self.max_bytes}}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != UPLOAD_ROUTE
        ):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                content_length = int(raw_length)
            except (TypeError, ValueError):
                await self._reject(
                    scope, receive, send, status_code=400, code="invalid_content_length"
                )
                return
            if content_length < 0:
                await self._reject(
                    scope, receive, send, status_code=400, code="invalid_content_length"
                )
                return
            if content_length > self.max_bytes:
                await self._reject(
                    scope, receive, send, status_code=413, code="upload_request_too_large"
                )
                return

        received = 0
        too_large = False
        response_started = False
        overflow_body = json.dumps(
            {
                "detail": {
                    "code": "upload_request_too_large",
                    "max_request_bytes": self.max_bytes,
                }
            }
        ).encode()

        async def limited_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    too_large = True
                    return {"type": "http.disconnect"}
            return message

        async def limited_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                if too_large:
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 413,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(overflow_body)).encode()),
                                (b"cache-control", b"no-store"),
                            ],
                        }
                    )
                    return
            if message["type"] == "http.response.body" and too_large:
                await send(
                    {
                        "type": "http.response.body",
                        "body": overflow_body,
                        "more_body": False,
                    }
                )
                return
            await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except Exception:
            if too_large and not response_started:
                await self._reject(
                    scope, receive, send, status_code=413, code="upload_request_too_large"
                )
                return
            raise

        if too_large and not response_started:
            await self._reject(
                scope, receive, send, status_code=413, code="upload_request_too_large"
            )
