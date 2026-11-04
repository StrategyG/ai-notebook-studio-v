from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_notebook_api.db.models import OutboxEvent
from ai_notebook_api.db.session import apply_tenant_database_context


class OutboxLeaseError(PermissionError):
    """The worker does not own a live lease for this outbox event."""


def _validate_identifier(value: str, *, name: str, limit: int) -> None:
    if not value or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be non-empty and at most {limit} characters")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def append_outbox_event(
    session: Session,
    *,
    tenant_id: UUID,
    idempotency_key: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
    available_at: datetime | None = None,
) -> OutboxEvent:
    """Append an event in the caller's business transaction; unique key provides deduplication."""
    _validate_identifier(idempotency_key, name="idempotency_key", limit=128)
    _validate_identifier(event_type, name="event_type", limit=128)
    _validate_identifier(aggregate_type, name="aggregate_type", limit=128)
    _validate_identifier(aggregate_id, name="aggregate_id", limit=255)
    if not isinstance(payload, dict):
        raise TypeError("outbox payload must be a JSON object")
    if available_at is not None and (
        available_at.tzinfo is None or available_at.utcoffset() is None
    ):
        raise ValueError("available_at must be timezone-aware")

    apply_tenant_database_context(session, str(tenant_id))
    event = OutboxEvent(
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload,
        available_at=available_at or datetime.now(UTC),
    )
    session.add(event)
    session.flush()
    return event


def claim_outbox_events(
    session: Session,
    *,
    tenant_id: UUID,
    worker_id: str,
    batch_size: int = 20,
    lease_seconds: int = 60,
    now: datetime | None = None,
) -> list[OutboxEvent]:
    _validate_identifier(worker_id, name="worker_id", limit=128)
    if not 1 <= batch_size <= 100 or not 5 <= lease_seconds <= 3600:
        raise ValueError("batch_size must be 1..100 and lease_seconds must be 5..3600")
    if now is not None and (now.tzinfo is None or now.utcoffset() is None):
        raise ValueError("claim time must be timezone-aware")
    current_time = _utc(now or datetime.now(UTC))

    apply_tenant_database_context(session, str(tenant_id))
    events = session.scalars(
        select(OutboxEvent)
        .where(
            OutboxEvent.tenant_id == tenant_id,
            OutboxEvent.published_at.is_(None),
            OutboxEvent.available_at <= current_time,
            (OutboxEvent.locked_until.is_(None) | (OutboxEvent.locked_until < current_time)),
        )
        .order_by(OutboxEvent.created_at.asc(), OutboxEvent.id.asc())
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    ).all()

    for event in events:
        event.locked_by = worker_id
        event.locked_until = current_time + timedelta(seconds=lease_seconds)
        event.attempts += 1
    session.flush()
    return list(events)


def mark_outbox_published(
    session: Session,
    *,
    tenant_id: UUID,
    event_id: UUID,
    worker_id: str,
    published_at: datetime | None = None,
    now: datetime | None = None,
) -> OutboxEvent:
    if now is not None and (now.tzinfo is None or now.utcoffset() is None):
        raise ValueError("acknowledgement time must be timezone-aware")
    if published_at is not None and (
        published_at.tzinfo is None or published_at.utcoffset() is None
    ):
        raise ValueError("published_at must be timezone-aware")
    current_time = _utc(now or datetime.now(UTC))
    apply_tenant_database_context(session, str(tenant_id))
    event = session.scalar(
        select(OutboxEvent)
        .where(OutboxEvent.id == event_id, OutboxEvent.tenant_id == tenant_id)
        .with_for_update()
    )
    if (
        event is None
        or event.published_at is not None
        or event.locked_by != worker_id
        or event.locked_until is None
        or _utc(event.locked_until) <= current_time
    ):
        raise OutboxLeaseError("worker does not own a live lease for this outbox event")
    event.published_at = published_at or current_time
    event.locked_by = None
    event.locked_until = None
    event.last_error = None
    session.flush()
    return event


def release_outbox_event(
    session: Session,
    *,
    tenant_id: UUID,
    event_id: UUID,
    worker_id: str,
    error: str,
    retry_after_seconds: int = 30,
    now: datetime | None = None,
) -> OutboxEvent:
    if not 1 <= retry_after_seconds <= 86_400:
        raise ValueError("retry_after_seconds must be 1..86400")
    if not error or not error.strip():
        raise ValueError("error detail is required")
    if now is not None and (now.tzinfo is None or now.utcoffset() is None):
        raise ValueError("release time must be timezone-aware")
    current_time = _utc(now or datetime.now(UTC))

    apply_tenant_database_context(session, str(tenant_id))
    event = session.scalar(
        select(OutboxEvent)
        .where(OutboxEvent.id == event_id, OutboxEvent.tenant_id == tenant_id)
        .with_for_update()
    )
    if (
        event is None
        or event.published_at is not None
        or event.locked_by != worker_id
        or event.locked_until is None
        or _utc(event.locked_until) <= current_time
    ):
        raise OutboxLeaseError("worker does not own a live lease for this outbox event")
    event.available_at = current_time + timedelta(seconds=retry_after_seconds)
    event.locked_by = None
    event.locked_until = None
    event.last_error = error[:2048]
    session.flush()
    return event
