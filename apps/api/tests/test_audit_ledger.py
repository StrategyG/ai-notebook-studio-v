from collections.abc import Generator
from uuid import UUID

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from ai_notebook_api.db.base import Base
from ai_notebook_api.db.models import AuditEvent
from ai_notebook_api.services.audit import append_audit_event, verify_audit_chain

TENANT_A = UUID("d2719d9a-3b0a-4b8a-a95b-1a8a1efc7f8e")
TENANT_B = UUID("a8e49d50-9f30-4bde-9c6f-4a7d84b0d21c")


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def append(session: Session, *, tenant_id=TENANT_A, action="notebook.created", payload=None):
    return append_audit_event(
        session,
        tenant_id=tenant_id,
        actor_subject="user-1",
        action=action,
        resource_type="notebook",
        resource_id="notebook-1",
        request_id="req-1",
        payload=payload or {"source": "api"},
    )


def test_audit_events_form_a_valid_per_tenant_hash_chain(session: Session) -> None:
    first = append(session)
    second = append(session, action="notebook.updated")
    other_tenant = append(session, tenant_id=TENANT_B)
    session.commit()

    assert first.sequence == 1
    assert second.sequence == 2
    assert second.previous_hash == first.event_hash
    assert other_tenant.sequence == 1
    assert verify_audit_chain(session, tenant_id=TENANT_A)
    assert verify_audit_chain(session, tenant_id=TENANT_B)


def test_audit_chain_detects_payload_tampering(session: Session) -> None:
    event = append(session)
    session.commit()

    session.execute(
        update(AuditEvent)
        .where(AuditEvent.id == event.id)
        .values(payload={"source": "tampered"})
    )
    session.commit()

    assert not verify_audit_chain(session, tenant_id=TENANT_A)


def test_audit_append_rejects_missing_actor_or_request_id(session: Session) -> None:
    with pytest.raises(ValueError, match="identifiers are required"):
        append_audit_event(
            session,
            tenant_id=TENANT_A,
            actor_subject="",
            action="notebook.created",
            resource_type="notebook",
            resource_id="notebook-1",
            request_id="req-1",
        )


def test_audit_append_rejects_non_object_payload(session: Session) -> None:
    with pytest.raises(TypeError, match="JSON object"):
        append_audit_event(
            session,
            tenant_id=TENANT_A,
            actor_subject="user-1",
            action="notebook.created",
            resource_type="notebook",
            resource_id="notebook-1",
            request_id="req-1",
            payload=["not-a-json-object"],
        )
