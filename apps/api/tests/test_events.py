from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ai_notebook_api.domain.events import EventEnvelope


def test_event_envelope_has_stable_correlation_and_idempotency_fields() -> None:
    event = EventEnvelope(
        event_type="task.status.changed",
        project_id=uuid4(),
        actor_id="agent:planner",
        source="orchestrator",
        target="workspace-stream",
        correlation_id=uuid4(),
        idempotency_key="a-stable-idempotency-key",
        aggregate_id="task:123",
        aggregate_version=2,
        payload={"from": "PLANNED", "to": "ASSIGNED"},
    )
    assert event.event_id
    assert event.schema_version == "1.0"
    assert event.aggregate_version == 2


def test_event_envelope_rejects_naive_timestamp_and_bad_version() -> None:
    with pytest.raises(ValidationError):
        EventEnvelope(
            event_type="task.created", project_id=uuid4(), actor_id="user:1",
            source="api", target="task-registry", correlation_id=uuid4(),
            idempotency_key="a-stable-idempotency-key", aggregate_id="task:1",
            aggregate_version=0, occurred_at=datetime(2026, 1, 1),
        )


def test_event_payload_is_bounded() -> None:
    with pytest.raises(ValidationError, match="64"):
        EventEnvelope(
            event_type="task.created", project_id=uuid4(), actor_id="user:1",
            source="api", target="task-registry", correlation_id=uuid4(),
            idempotency_key="a-stable-idempotency-key", aggregate_id="task:1",
            aggregate_version=1, payload={str(i): i for i in range(65)},
        )
