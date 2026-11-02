from fastapi import FastAPI

from ai_notebook_api import __version__
from ai_notebook_api.api.health import router as health_router

app = FastAPI(
    title="AI Notebook Studio API",
    version=__version__,
    description=(
        "Stage 1 modular API foundation. Business routes remain gated until "
        "authentication, persistence and authorization are implemented."
    ),
)
app.include_router(health_router)


@app.get("/api/v1/meta", tags=["platform"])
def platform_metadata() -> dict[str, object]:
    return {
        "name": "AI Notebook Studio",
        "api_version": "v1",
        "implementation_stage": "stage-1-foundation-skeleton",
        "production_ready": False,
    }
