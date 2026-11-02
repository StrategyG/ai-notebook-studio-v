from fastapi import FastAPI

from ai_notebook_api import __version__
from ai_notebook_api.api.health import router as health_router
from ai_notebook_api.api.identity import router as identity_router

app = FastAPI(
    title="AI Notebook Studio API",
    version=__version__,
    description=(
        "V6 security foundation. Verified identity is available, while tenant membership, "
        "persistence and business routes remain gated until their controls are implemented."
    ),
)
app.include_router(health_router)
app.include_router(identity_router)


@app.get("/api/v1/meta", tags=["platform"])
def platform_metadata() -> dict[str, object]:
    return {
        "name": "AI Notebook Studio",
        "api_version": "v1",
        "implementation_stage": "v6-jwt-verification-foundation",
        "production_ready": False,
    }
