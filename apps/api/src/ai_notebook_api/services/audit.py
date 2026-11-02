from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ai_notebook_api.db.models import AuditEvent
from ai_notebook_api.db.session import apply_tenant_database_context

GENESIS_HASH = "0" * 64


def _canonical_event(
    *,
    tenant_id: UUID,
    sequence: int,
    actor_subject: str,
    action: str,
    resource_type: str,
    resource_id: str,
    request_id: str,
    payload: dict[str, Any],
    previous_hash: str,
    occurred_at: datetime,
) -> bytes:
    normalized_time = (
        occurred_at.replace(tzinfo=UTC)
        if occurred_at.tzinfo is None
        else occurred_at.astimezone(UTC)
    )
    value = {
        "tenant_id": str(tenant_id),
        "sequence": sequence,
        "actor_subject": actor_subject,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "request_id": request_id,
        "payload": payload,
        "previous_hash": previous_hash,
        "occurred_at": normalized_time.isoformat(),
    }
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")


def append_audit_event(
    session: Session,
    *,
    tenant_id: UUID,
    actor_subject: str,
    action: str,
    resource_type: str,
    resource_id: str,
    request_id: str,
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append a tenant-scoped hash-chained event; caller owns transaction commit."""
    values = (actor_subject, action, resource_type, resource_id, request_id)
    if any(not value or not value.strip() for value in values):
        raise ValueError("audit actor, action, resource and request identifiers are required")
    limits = (255, 128, 128, 255, 128)
    if any(len(value) > limit for value, limit in zip(values, limits, strict=True)):
        raise ValueError("audit identifier exceeds its storage limit")
    if payload is not None and not isinstance(payload, dict):
        raise TypeError("audit payload must be a JSON object")

    apply_tenant_database_context(session, str(tenant_id))
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant_id, 0))"),
            {"tenant_id": str(tenant_id)},
        )

    previous = session.scalar(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.sequence.desc())
        .limit(1)
    )
    sequence = 1 if previous is None else previous.sequence + 1
    previous_hash = GENESIS_HASH if previous is None else previous.event_hash
    occurred_at = datetime.now(UTC)
    event_payload = payload or {}
    digest = hashlib.sha256(
        _canonical_event(
            tenant_id=tenant_id,
            sequence=sequence,
            actor_subject=actor_subject,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id,
            payload=event_payload,
            previous_hash=previous_hash,
            occurred_at=occurred_at,
        )
    ).hexdigest()
    event = AuditEvent(
        tenant_id=tenant_id,
        sequence=sequence,
        actor_subject=actor_subject,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        payload=event_payload,
        previous_hash=previous_hash,
        event_hash=digest,
        occurred_at=occurred_at,
    )
    session.add(event)
    session.flush()
    return event


def verify_audit_chain(session: Session, *, tenant_id: UUID) -> bool:
    apply_tenant_database_context(session, str(tenant_id))
    events = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.sequence.asc())
    ).all()
    previous_hash = GENESIS_HASH
    for expected_sequence, event in enumerate(events, start=1):
        if event.sequence != expected_sequence or event.previous_hash != previous_hash:
            return False
        calculated = hashlib.sha256(
            _canonical_event(
                tenant_id=event.tenant_id,
                sequence=event.sequence,
                actor_subject=event.actor_subject,
                action=event.action,
                resource_type=event.resource_type,
                resource_id=event.resource_id,
                request_id=event.request_id,
                payload=event.payload,
                previous_hash=event.previous_hash,
                occurred_at=event.occurred_at,
            )
        ).hexdigest()
        if calculated != event.event_hash:
            return False
        previous_hash = event.event_hash
    return True
