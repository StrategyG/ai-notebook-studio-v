from uuid import uuid4

import pytest
from pydantic import ValidationError

from ai_notebook_api.domain.agent_registry import AgentDescriptor, AgentHealth, ProtocolName


def make_agent(**overrides):
    values = {
        "agent_id": "repo-analyst.v1",
        "name": "Repository Analyst",
        "version": "1.0.0",
        "description": "Read-only repository inspection agent.",
        "capabilities": {"repository.inspect", "dependency.audit"},
        "supported_task_types": {"repository.audit"},
        "supported_protocols": {ProtocolName.INTERNAL, ProtocolName.A2A},
        "health": AgentHealth.AVAILABLE,
    }
    return AgentDescriptor(**(values | overrides))


def test_registry_eligibility_checks_capability_task_and_scope() -> None:
    tenant_id, project_id = uuid4(), uuid4()
    agent = make_agent(tenant_id=tenant_id, project_id=project_id)
    assert agent.is_eligible(
        capabilities={"repository.inspect"}, task_type="repository.audit",
        tenant_id=tenant_id, project_id=project_id,
    )
    assert not agent.is_eligible(
        capabilities={"repository.write"}, task_type="repository.audit",
        tenant_id=tenant_id, project_id=project_id,
    )
    assert not agent.is_eligible(
        capabilities={"repository.inspect"}, task_type="repository.audit",
        tenant_id=uuid4(), project_id=project_id,
    )


def test_offline_agent_is_never_eligible() -> None:
    agent = make_agent(health=AgentHealth.OFFLINE)
    assert not agent.is_eligible(
        capabilities={"repository.inspect"}, task_type="repository.audit",
        tenant_id=uuid4(), project_id=uuid4(),
    )


def test_project_scoped_agent_requires_tenant_scope() -> None:
    with pytest.raises(ValidationError, match="tenant_id"):
        make_agent(project_id=uuid4())


def test_registry_rejects_unknown_fields_and_whitespace_capability() -> None:
    with pytest.raises(ValidationError):
        make_agent(admin=True)
    with pytest.raises(ValidationError):
        make_agent(capabilities={"repository inspect"})
