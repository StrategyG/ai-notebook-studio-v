import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from ai_notebook_api.upload_limits import UPLOAD_ROUTE, UploadBodyLimitMiddleware


def _test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(UploadBodyLimitMiddleware, max_bytes=8)

    @app.post(UPLOAD_ROUTE)
    async def upload(request: Request) -> dict[str, int]:
        return {"received_bytes": len(await request.body())}

    return app


def test_upload_middleware_accepts_a_body_at_the_limit() -> None:
    response = TestClient(_test_app()).post(UPLOAD_ROUTE, content=b"12345678")

    assert response.status_code == 200
    assert response.json()["received_bytes"] == 8


def test_upload_middleware_rejects_content_length_over_the_limit_before_parsing() -> None:
    response = TestClient(_test_app()).post(UPLOAD_ROUTE, content=b"123456789")

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "upload_request_too_large"


@pytest.mark.asyncio
async def test_upload_middleware_rejects_streamed_body_without_content_length() -> None:
    async def body_chunks():
        yield b"1234"
        yield b"56789"

    async with AsyncClient(
        transport=ASGITransport(app=_test_app()),
        base_url="http://testserver",
    ) as client:
        response = await client.post(UPLOAD_ROUTE, content=body_chunks())

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "upload_request_too_large"


def test_upload_middleware_does_not_limit_other_routes() -> None:
    app = FastAPI()
    app.add_middleware(UploadBodyLimitMiddleware, max_bytes=8)

    @app.post("/api/v1/other")
    async def other(request: Request) -> dict[str, int]:
        return {"received_bytes": len(await request.body())}

    response = TestClient(app).post("/api/v1/other", content=b"123456789")

    assert response.status_code == 200
    assert response.json()["received_bytes"] == 9



@pytest.mark.parametrize("max_bytes", [0, -1, True, 1.5])
def test_upload_middleware_rejects_invalid_limit_configuration(max_bytes: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        UploadBodyLimitMiddleware(_test_app(), max_bytes=max_bytes)
