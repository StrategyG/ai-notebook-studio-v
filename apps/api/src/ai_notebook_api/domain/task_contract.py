from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TaskState(StrEnum):
    CREATED = "CREATED"
    PLANNED = "PLANNED"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    REVIEW = "REVIEW"
    VALIDATION = "VALIDATION"
    APPROVAL = "APPROVAL"
    COMPLETED = "COMPLETED"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class RiskClass(StrEnum):
    READ = "READ"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ActorRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: str = Field(min_length=1, max_length=128)
    actor_type: str = Field(pattern="^(user|agent|system)$")


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: UUID
    sha256: str = Field(pattern="^[a-f0-9]{64}$")
    media_type: str = Field(min_length=1, max_length=128)
    trust: str = Field(default="untrusted", pattern="^(untrusted|validated|trusted)$")


class TaskContract(BaseModel):
    """Versioned domain task contract; persistence and A2A wire mapping are separate."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    task_id: UUID
    parent_task_id: UUID | None = None
    project_id: UUID
    requested_by: ActorRef
    assigned_agent_id: str | None = None
    objective: str = Field(min_length=1, max_length=8_000)
    input_refs: list[ArtifactRef] = Field(default_factory=list, max_length=100)
    required_capabilities: set[str] = Field(default_factory=set, max_length=64)
    permission_scope: set[str] = Field(default_factory=set, max_length=128)
    risk_class: RiskClass = RiskClass.READ
    expected_artifacts: list[str] = Field(default_factory=list, max_length=50)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=100)
    timeout_seconds: int = Field(ge=1, le=86_400)
    budget_usd: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=4)
    dependencies: set[UUID] = Field(default_factory=set, max_length=100)
    idempotency_key: str = Field(min_length=16, max_length=128)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    state: TaskState = TaskState.CREATED

    @field_validator("required_capabilities", "permission_scope")
    @classmethod
    def validate_scope_names(cls, values: set[str]) -> set[str]:
        for item in values:
            if not item or len(item) > 128 or any(ch.isspace() for ch in item):
                raise ValueError("scope/capability names must be non-empty tokens")
        return values

    @field_validator("dependencies")
    @classmethod
    def reject_self_dependency(cls, values: set[UUID], info: Any) -> set[UUID]:
        task_id = info.data.get("task_id")
        if task_id is not None and task_id in values:
            raise ValueError("task cannot depend on itself")
        return values

    @field_validator("parent_task_id")
    @classmethod
    def reject_self_parent(cls, value: UUID | None, info: Any) -> UUID | None:
        if value is not None and value == info.data.get("task_id"):
            raise ValueError("task cannot be its own parent")
        return value
