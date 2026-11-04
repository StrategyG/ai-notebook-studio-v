from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ai_notebook_api.core.config import Settings
from ai_notebook_api.db.base import Base
from ai_notebook_api.db.models import TenantMembership
from ai_notebook_api.db.session import get_engine, get_tenant_session
from ai_notebook_api.main import app
from ai_notebook_api.security.auth import Principal, get_current_principal
from ai_notebook_api.security.tenant import (
    TenantAuthorizationError,
    require_tenant_permissions,
    resolve_active_membership,
)

TENANT_A = UUID("d2719d9a-3b0a-4b8a-a95b-1a8a1efc7f8e")
TENANT_B = UUID("a8e49d50-9f30-4bde-9c6f-4a7d84b0d21c")
OIDC_ISSUER = "https://identity.example/"
OTHER_OIDC_ISSUER = "https://other-identity.example/"
PRINCIPAL = Principal(
    issuer=OIDC_ISSUER,
    subject="user-1",
    tenant_id=TENANT_A,
    roles=frozenset({"owner"}),
    scopes=frozenset({"tenant:read"}),
)


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def test_active_membership_is_resolved_from_database_not_token_roles(session: Session) -> None:
    session.add(
        TenantMembership(
            tenant_id=TENANT_A,
            issuer=OIDC_ISSUER,
            subject="user-1",
            role="admin",
            status="active",
        )
    )
    session.commit()

    membership = resolve_active_membership(session, issuer=OIDC_ISSUER, subject="user-1", tenant_id=TENANT_A)

    assert membership.role == "admin"
    assert membership.status == "active"


def test_membership_resolution_is_scoped_to_issuer_and_subject(session: Session) -> None:
    session.add_all(
        [
            TenantMembership(
                tenant_id=TENANT_A,
                issuer=OIDC_ISSUER,
                subject="same-subject",
                role="viewer",
                status="active",
            ),
            TenantMembership(
                tenant_id=TENANT_A,
                issuer=OTHER_OIDC_ISSUER,
                subject="same-subject",
                role="admin",
                status="active",
            ),
        ]
    )
    session.commit()

    membership = resolve_active_membership(
        session,
        issuer=OTHER_OIDC_ISSUER,
        subject="same-subject",
        tenant_id=TENANT_A,
    )
    assert membership.role == "admin"

    with pytest.raises(TenantAuthorizationError):
        resolve_active_membership(
            session,
            issuer="https://untrusted-identity.example/",
            subject="same-subject",
            tenant_id=TENANT_A,
        )


def test_legacy_membership_without_issuer_never_authorizes(session: Session) -> None:
    session.add(
        TenantMembership(
            tenant_id=TENANT_A,
            issuer=None,
            subject="legacy-user",
            role="owner",
            status="active",
        )
    )
    session.commit()

    with pytest.raises(TenantAuthorizationError):
        resolve_active_membership(
            session,
            issuer=OIDC_ISSUER,
            subject="legacy-user",
            tenant_id=TENANT_A,
        )


def test_api_membership_rejects_supabase_only_role(session: Session) -> None:
    session.add(
        TenantMembership(
            tenant_id=TENANT_A,
            issuer=OIDC_ISSUER,
            subject="user-1",
            role="billing_viewer",
            status="active",
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_membership_from_another_tenant_is_not_authorized(session: Session) -> None:
    session.add(
        TenantMembership(
            tenant_id=TENANT_B,
            issuer=OIDC_ISSUER,
            subject="user-1",
            role="owner",
            status="active",
        )
    )
    session.commit()

    with pytest.raises(TenantAuthorizationError):
        resolve_active_membership(session, issuer=OIDC_ISSUER, subject="user-1", tenant_id=TENANT_A)


def test_suspended_membership_is_not_authorized(session: Session) -> None:
    session.add(
        TenantMembership(
            tenant_id=TENANT_A,
            issuer=OIDC_ISSUER,
            subject="user-1",
            role="member",
            status="suspended",
        )
    )
    session.commit()

    with pytest.raises(TenantAuthorizationError):
        resolve_active_membership(session, issuer=OIDC_ISSUER, subject="user-1", tenant_id=TENANT_A)


def test_missing_membership_is_not_authorized(session: Session) -> None:
    with pytest.raises(TenantAuthorizationError):
        resolve_active_membership(session, issuer=OIDC_ISSUER, subject="unknown", tenant_id=TENANT_A)


def test_tenant_context_endpoint_returns_database_role(session: Session) -> None:
    session.add(
        TenantMembership(
            tenant_id=TENANT_A,
            issuer=OIDC_ISSUER,
            subject="user-1",
            role="admin",
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
        "role": "admin",
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


def test_tenant_permission_dependency_uses_database_role(session: Session) -> None:
    session.add(
        TenantMembership(
            tenant_id=TENANT_A,
            issuer=OIDC_ISSUER,
            subject="user-1",
            role="viewer",
            status="active",
        )
    )
    session.commit()
    membership = resolve_active_membership(session, issuer=OIDC_ISSUER, subject="user-1", tenant_id=TENANT_A)

    dependency = require_tenant_permissions("notebooks:write")
    with pytest.raises(HTTPException) as error:
        dependency(membership)
    assert error.value.status_code == 403


def test_tenant_permission_dependency_allows_owner(session: Session) -> None:
    session.add(
        TenantMembership(
            tenant_id=TENANT_A,
            issuer=OIDC_ISSUER,
            subject="user-1",
            role="owner",
            status="active",
        )
    )
    session.commit()
    membership = resolve_active_membership(session, issuer=OIDC_ISSUER, subject="user-1", tenant_id=TENANT_A)

    dependency = require_tenant_permissions("members:manage", "providers:manage")
    assert dependency(membership) is membership


def test_engine_normalizes_postgresql_url_to_psycopg() -> None:
    engine = get_engine("postgresql://user:password@localhost:5432/app")
    try:
        assert engine.url.drivername == "postgresql+psycopg"
    finally:
        engine.dispose()
        get_engine.cache_clear()


def test_tenant_session_fails_closed_without_database_configuration() -> None:
    dependency = get_tenant_session(Settings())
    with pytest.raises(HTTPException) as error:
        next(dependency)
    assert error.value.status_code == 503
