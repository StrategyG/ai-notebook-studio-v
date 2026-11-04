from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_notebook_api.core.config import Settings, get_settings


@lru_cache(maxsize=8)
def get_engine(database_url: str) -> Engine:
    """Create a process-local pool for a deployment-configured database URL."""
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return create_engine(database_url, pool_pre_ping=True, pool_recycle=300)


def get_tenant_session(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Generator[Session, None, None]:
    if not settings.persistence_configured or not settings.database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tenant persistence is not configured",
        )

    factory = sessionmaker(bind=get_engine(settings.database_url), expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


def apply_tenant_database_context(session: Session, tenant_id: str) -> None:
    """Set transaction-local tenant context consumed by PostgreSQL RLS policies."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )
