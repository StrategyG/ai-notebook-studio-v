from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ai_notebook_api import __version__
from ai_notebook_api.api.health import router as health_router
from ai_notebook_api.api.identity import router as identity_router
from ai_notebook_api.api.tasks import router as task_router
from ai_notebook_api.api.tenant import router as tenant_router
from ai_notebook_api.core.config import get_settings, validate_ugai_configuration
from ai_notebook_api.services.ugai_client import (
    OAuthTokenExchangeProvider,
    UGAITaskClient,
)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    validate_ugai_configuration(settings)
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
        yield
    finally:
        if client is not None:
            await client.aclose()


app = FastAPI(
    title="AI Notebook Studio API",
    version=__version__,
    description=(
        "Tenant-scoped Notebook API. UGAI task submission is available only "
        "when server-side OAuth token exchange is configured."
    ),
    lifespan=lifespan,
)
app.include_router(health_router)
app.include_router(identity_router)
app.include_router(tenant_router)
app.include_router(task_router)


@app.get("/api/v1/meta", tags=["platform"])
def platform_metadata() -> dict[str, object]:
    settings = get_settings()
    return {
        "name": "AI Notebook Studio",
        "api_version": "v1",
        "implementation_stage": "v1-tenant-authorization-and-ugai-integration",
        "ugai_enabled": settings.ugai_enabled,
        "production_ready": False,
    }
