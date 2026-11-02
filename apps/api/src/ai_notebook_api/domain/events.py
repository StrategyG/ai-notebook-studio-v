from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventEnvelope(BaseModel):
    """Versioned event metadata; durable delivery requires a transactional outbox."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID = Field(default_factory=uuid4)
    event_type: str = Field(min_length=3, max_length=160, pattern=r"^[a-z][a-z0-9_.-]+$")
    project_id: UUID
    actor_id: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=128)
    target: str = Field(min_length=1, max_length=128)
    correlation_id: UUID
    idempotency_key: str = Field(min_length=16, max_length=128)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    aggregate_id: str = Field(min_length=1, max_length=160)
    aggregate_version: int = Field(ge=1)
    schema_version: str = Field(default="1.0", min_length=1, max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value

    @field_validator("payload")
    @classmethod
    def limit_payload_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 64:
            raise ValueError("event payload exceeds 64 top-level fields")
        return value
