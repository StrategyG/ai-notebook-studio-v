from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, HTTPException, status

from ai_notebook_api import __version__
from ai_notebook_api.api.health import router as health_router
from ai_notebook_api.api.identity import router as identity_router
from ai_notebook_api.api.rag import router as rag_router
from ai_notebook_api.api.rag_upload import router as rag_upload_router
from ai_notebook_api.api.tasks import router as task_router
from ai_notebook_api.api.tenant import router as tenant_router
from ai_notebook_api.core.config import (
    get_settings,
    validate_mcp_configuration,
    validate_rag_configuration,
    validate_ugai_configuration,
)
from ai_notebook_api.mcp_server import build_mcp_server
from ai_notebook_api.services.ugai_client import (
    OAuthTokenExchangeProvider,
    UGAITaskClient,
)
from ai_notebook_api.upload_limits import UploadBodyLimitMiddleware

_mcp_server, _mcp_asgi_app = build_mcp_server(get_settings())


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    validate_ugai_configuration(settings)
    validate_rag_configuration(settings)
    validate_mcp_configuration(settings)
    client = None
    application.state.ugai_task_client = None
    try:
        if settings.ugai_enabled:
            token_provider = OAuthTokenExchangeProvider(
                token_endpoint=settings.ugai_token_endpoint or "",
                client_id=settings.ugai_client_id or "",
                client_secret=settings.ugai_client_secret or "",
            )
            client = UGAITaskClient(
                base_url=settings.ugai_base_url or "",
                audience=settings.ugai_audience or "",
                token_provider=token_provider,
            )
            application.state.ugai_task_client = client

        async with AsyncExitStack() as stack:
            if _mcp_server is not None:
                await stack.enter_async_context(_mcp_server.session_manager.run())
            yield
    finally:
        if client is not None:
            await client.aclose()


app = FastAPI(
    title="AI Notebook Studio API",
    version=__version__,
    description=(
        "Tenant-scoped Notebook API with PostgreSQL RAG retrieval and an "
        "authenticated, allowlisted MCP Streamable HTTP endpoint when enabled."
    ),
    lifespan=lifespan,
)
app.add_middleware(UploadBodyLimitMiddleware)
app.include_router(health_router)
app.include_router(identity_router)
app.include_router(tenant_router)
app.include_router(task_router)
app.include_router(rag_router)
app.include_router(rag_upload_router)


@app.get("/api/v1/meta", tags=["platform"])
def platform_metadata() -> dict[str, object]:
    settings = get_settings()
    return {
        "name": "AI Notebook Studio",
        "api_version": "v1",
        "implementation_stage": "tenant-scoped-rag-and-mcp",
        "rag_enabled": settings.rag_enabled,
        "mcp_enabled": settings.mcp_enabled,
        "ugai_enabled": settings.ugai_enabled,
        "production_ready": False,
    }


if _mcp_asgi_app is not None:
    # Mount last: the root mount forwards /mcp and the OAuth protected-resource
    # metadata route while leaving the explicit FastAPI routes above reachable.
    app.mount("/", _mcp_asgi_app)
else:

    @app.api_route("/mcp", methods=["GET", "POST", "DELETE"], include_in_schema=False)
    async def mcp_unavailable() -> None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "mcp_not_enabled"},
        )
