from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from .task_contract import TaskState


class InvalidTaskTransition(ValueError):
    pass


TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.CREATED: frozenset({TaskState.PLANNED, TaskState.BLOCKED, TaskState.CANCELLED, TaskState.EXPIRED}),
    TaskState.PLANNED: frozenset({TaskState.ASSIGNED, TaskState.BLOCKED, TaskState.CANCELLED, TaskState.FAILED, TaskState.EXPIRED}),
    TaskState.ASSIGNED: frozenset({TaskState.RUNNING, TaskState.WAITING, TaskState.BLOCKED, TaskState.CANCELLED, TaskState.FAILED, TaskState.EXPIRED}),
    TaskState.RUNNING: frozenset({TaskState.WAITING, TaskState.REVIEW, TaskState.VALIDATION, TaskState.BLOCKED, TaskState.CANCELLED, TaskState.FAILED, TaskState.EXPIRED}),
    TaskState.WAITING: frozenset({TaskState.RUNNING, TaskState.BLOCKED, TaskState.CANCELLED, TaskState.FAILED, TaskState.EXPIRED}),
    TaskState.BLOCKED: frozenset({TaskState.PLANNED, TaskState.ASSIGNED, TaskState.CANCELLED, TaskState.FAILED, TaskState.EXPIRED}),
    TaskState.REVIEW: frozenset({TaskState.VALIDATION, TaskState.PLANNED, TaskState.BLOCKED, TaskState.CANCELLED, TaskState.FAILED}),
    TaskState.VALIDATION: frozenset({TaskState.APPROVAL, TaskState.REVIEW, TaskState.PLANNED, TaskState.BLOCKED, TaskState.CANCELLED, TaskState.FAILED}),
    TaskState.APPROVAL: frozenset({TaskState.COMPLETED, TaskState.PLANNED, TaskState.BLOCKED, TaskState.CANCELLED, TaskState.FAILED}),
    TaskState.COMPLETED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.CANCELLED: frozenset(),
    TaskState.EXPIRED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class TaskTransition:
    task_id: UUID
    from_state: TaskState
    to_state: TaskState
    actor_id: str
    reason: str
    occurred_at: datetime


def transition_task(
    *, task_id: UUID, current: TaskState, target: TaskState, actor_id: str, reason: str
) -> TaskTransition:
    if target not in TRANSITIONS[current]:
        raise InvalidTaskTransition(f"transition {current.value} -> {target.value} is not allowed")
    if not actor_id.strip() or not reason.strip():
        raise ValueError("actor_id and reason are required for an auditable transition")
    return TaskTransition(
        task_id=task_id,
        from_state=current,
        to_state=target,
        actor_id=actor_id,
        reason=reason,
        occurred_at=datetime.now(UTC),
    )
