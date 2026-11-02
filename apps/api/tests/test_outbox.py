from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ai_notebook_api.db.base import Base
from ai_notebook_api.services.outbox import (
    OutboxLeaseError,
    append_outbox_event,
    claim_outbox_events,
    mark_outbox_published,
    release_outbox_event,
)

TENANT_ID = UUID("d2719d9a-3b0a-4b8a-a95b-1a8a1efc7f8e")
NOW = datetime.now(UTC)


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def make_event(session: Session):
    return append_outbox_event(
        session,
        tenant_id=TENANT_ID,
        idempotency_key="notebook:123:created",
        event_type="notebook.created",
        aggregate_type="notebook",
        aggregate_id="123",
        payload={"notebook_id": "123"},
        available_at=NOW,
    )


def test_outbox_event_is_claimed_and_published_by_lease_owner(session: Session) -> None:
    event = make_event(session)
    session.commit()
    claimed = claim_outbox_events(session, tenant_id=TENANT_ID, worker_id="worker-a", now=NOW)
    assert [item.id for item in claimed] == [event.id]
    assert claimed[0].attempts == 1
    assert claimed[0].locked_by == "worker-a"
    session.commit()

    published = mark_outbox_published(
        session,
        tenant_id=TENANT_ID,
        event_id=event.id,
        worker_id="worker-a",
        published_at=NOW,
        now=NOW + timedelta(seconds=1),
    )
    session.commit()
    assert published.published_at.replace(tzinfo=UTC) == NOW
    assert published.locked_by is None


def test_outbox_event_cannot_be_acknowledged_by_another_worker(session: Session) -> None:
    event = make_event(session)
    session.commit()
    claim_outbox_events(session, tenant_id=TENANT_ID, worker_id="worker-a", now=NOW)
    session.commit()

    with pytest.raises(OutboxLeaseError):
        mark_outbox_published(
            session,
            tenant_id=TENANT_ID,
            event_id=event.id,
            worker_id="worker-b",
            published_at=NOW,
            now=NOW + timedelta(seconds=1),
        )


def test_expired_worker_lease_cannot_acknowledge_event(session: Session) -> None:
    event = make_event(session)
    session.commit()
    claim_outbox_events(
        session, tenant_id=TENANT_ID, worker_id="worker-a", lease_seconds=5, now=NOW
    )
    session.commit()

    with pytest.raises(OutboxLeaseError):
        mark_outbox_published(
            session,
            tenant_id=TENANT_ID,
            event_id=event.id,
            worker_id="worker-a",
            now=NOW + timedelta(seconds=6),
        )


def test_outbox_failure_releases_event_with_bounded_retry(session: Session) -> None:
    event = make_event(session)
    session.commit()
    claim_outbox_events(session, tenant_id=TENANT_ID, worker_id="worker-a", now=NOW)
    session.commit()

    released = release_outbox_event(
        session,
        tenant_id=TENANT_ID,
        event_id=event.id,
        worker_id="worker-a",
        error="temporary provider failure",
        retry_after_seconds=60,
        now=NOW,
    )
    session.commit()
    assert released.available_at.replace(tzinfo=UTC) == NOW + timedelta(seconds=60)
    assert released.last_error == "temporary provider failure"
    assert claim_outbox_events(
        session, tenant_id=TENANT_ID, worker_id="worker-b", now=NOW
    ) == []
    assert len(
        claim_outbox_events(
            session, tenant_id=TENANT_ID, worker_id="worker-b", now=NOW + timedelta(seconds=61)
        )
    ) == 1


def test_outbox_rejects_invalid_payload_and_lease_bounds(session: Session) -> None:
    with pytest.raises(TypeError, match="JSON object"):
        append_outbox_event(
            session,
            tenant_id=TENANT_ID,
            idempotency_key="x",
            event_type="notebook.created",
            aggregate_type="notebook",
            aggregate_id="123",
            payload=["invalid"],
        )
    with pytest.raises(ValueError, match="lease_seconds"):
        claim_outbox_events(
            session, tenant_id=TENANT_ID, worker_id="worker-a", lease_seconds=1, now=NOW
        )
