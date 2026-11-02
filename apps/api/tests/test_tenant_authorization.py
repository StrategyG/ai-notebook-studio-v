from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ai_notebook_api.db.base import Base
from ai_notebook_api.db.models import TenantMembership
from ai_notebook_api.db.session import get_tenant_session
from ai_notebook_api.main import app
from ai_notebook_api.security.auth import Principal, get_current_principal
from ai_notebook_api.security.tenant import TenantAuthorizationError, resolve_active_membership

TENANT_A = UUID("d2719d9a-3b0a-4b8a-a95b-1a8a1efc7f8e")
TENANT_B = UUID("a8e49d50-9f30-4bde-9c6f-4a7d84b0d21c")
PRINCIPAL = Principal(
    subject="user-1",
    tenant_id=TENANT_A,
    roles=frozenset({"owner"}),
    scopes=frozenset({"tenant:read"}),
)


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def test_active_membership_is_resolved_from_database_not_token_roles(session: Session) -> None:
    session.add(
        TenantMembership(
            tenant_id=TENANT_A,
            subject="user-1",
            role="workspace_admin",
            status="active",
        )
    )
    session.commit()

    membership = resolve_active_membership(session, subject="user-1", tenant_id=TENANT_A)

    assert membership.role == "workspace_admin"
    assert membership.status == "active"


def test_membership_from_another_tenant_is_not_authorized(session: Session) -> None:
    session.add(
        TenantMembership(
            tenant_id=TENANT_B,
            subject="user-1",
            role="owner",
            status="active",
        )
    )
    session.commit()

    with pytest.raises(TenantAuthorizationError):
        resolve_active_membership(session, subject="user-1", tenant_id=TENANT_A)


def test_suspended_membership_is_not_authorized(session: Session) -> None:
    session.add(
        TenantMembership(
            tenant_id=TENANT_A,
            subject="user-1",
            role="member",
            status="suspended",
        )
    )
    session.commit()

    with pytest.raises(TenantAuthorizationError):
        resolve_active_membership(session, subject="user-1", tenant_id=TENANT_A)


def test_missing_membership_is_not_authorized(session: Session) -> None:
    with pytest.raises(TenantAuthorizationError):
        resolve_active_membership(session, subject="unknown", tenant_id=TENANT_A)


def test_tenant_context_endpoint_returns_database_role(session: Session) -> None:
    session.add(
        TenantMembership(
            tenant_id=TENANT_A,
            subject="user-1",
            role="workspace_admin",
            status="active",
        )
    )
    session.commit()

    def override_session():
        yield session

    app.dependency_overrides[get_current_principal] = lambda: PRINCIPAL
    app.dependency_overrides[get_tenant_session] = override_session
    try:
        response = TestClient(app).get("/api/v1/tenant/context")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": str(TENANT_A),
        "subject": "user-1",
        "role": "workspace_admin",
        "status": "active",
    }


def test_tenant_context_endpoint_denies_missing_membership(session: Session) -> None:
    def override_session():
        yield session

    app.dependency_overrides[get_current_principal] = lambda: PRINCIPAL
    app.dependency_overrides[get_tenant_session] = override_session
    try:
        response = TestClient(app).get("/api/v1/tenant/context")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
