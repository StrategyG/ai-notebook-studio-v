from uuid import uuid4

import pytest

from ai_notebook_api.domain.lifecycle import InvalidTaskTransition, transition_task
from ai_notebook_api.domain.task_contract import TaskState


def test_happy_path_requires_review_validation_and_approval() -> None:
    task_id = uuid4()
    state = TaskState.CREATED
    for next_state in [
        TaskState.PLANNED,
        TaskState.ASSIGNED,
        TaskState.RUNNING,
        TaskState.REVIEW,
        TaskState.VALIDATION,
        TaskState.APPROVAL,
        TaskState.COMPLETED,
    ]:
        transition = transition_task(
            task_id=task_id,
            current=state,
            target=next_state,
            actor_id="test-agent",
            reason="acceptance test",
        )
        assert transition.from_state == state
        assert transition.to_state == next_state
        assert transition.actor_id == "test-agent"
        state = next_state


def test_terminal_state_cannot_be_reopened() -> None:
    with pytest.raises(InvalidTaskTransition):
        transition_task(
            task_id=uuid4(),
            current=TaskState.COMPLETED,
            target=TaskState.RUNNING,
            actor_id="test-agent",
            reason="invalid restart",
        )


def test_transition_requires_audit_actor_and_reason() -> None:
    with pytest.raises(ValueError):
        transition_task(
            task_id=uuid4(),
            current=TaskState.CREATED,
            target=TaskState.PLANNED,
            actor_id="",
            reason="missing actor",
        )
