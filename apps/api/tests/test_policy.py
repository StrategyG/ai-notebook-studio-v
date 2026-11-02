from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ai_notebook_api.domain.task_contract import RiskClass
from ai_notebook_api.security.policy import (
    ApprovalEvidence,
    ApprovalRequired,
    ApprovalStatus,
    AuthorizationDenied,
    EffectiveGrant,
    authorize_delegation,
    intersect_grants,
    require_approval,
)


def test_grants_intersect_not_union() -> None:
    tenant_id, project_id = uuid4(), uuid4()
    user = EffectiveGrant(tenant_id, project_id, frozenset({"repo.read", "repo.write"}), frozenset({"inspect", "patch"}))
    agent = EffectiveGrant(tenant_id, project_id, frozenset({"repo.read"}), frozenset({"inspect"}))
    effective = intersect_grants(user, agent)
    assert effective.actions == frozenset({"repo.read"})
    assert effective.capabilities == frozenset({"inspect"})
    authorize_delegation(effective_grant=effective, requested_actions={"repo.read"}, requested_capabilities={"inspect"})
    with pytest.raises(AuthorizationDenied):
        authorize_delegation(effective_grant=effective, requested_actions={"repo.write"}, requested_capabilities={"patch"})


def test_grants_from_different_projects_cannot_be_combined() -> None:
    with pytest.raises(AuthorizationDenied):
        intersect_grants(
            EffectiveGrant(uuid4(), uuid4(), frozenset({"read"}), frozenset()),
            EffectiveGrant(uuid4(), uuid4(), frozenset({"read"}), frozenset()),
        )


def test_high_risk_requires_exact_current_action_approval() -> None:
    tenant_id, project_id = uuid4(), uuid4()
    digest = "a" * 64
    evidence = ApprovalEvidence(
        approval_id=uuid4(),
        approved_by="human-reviewer",
        tenant_id=tenant_id,
        project_id=project_id,
        target="repo:acme/test:branch/feature-x",
        operation="create_pull_request",
        risk_class=RiskClass.HIGH,
        content_sha256=digest,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        status=ApprovalStatus.APPROVED,
    )
    require_approval(
        risk_class=RiskClass.HIGH,
        evidence=evidence,
        target="repo:acme/test:branch/feature-x",
        operation="create_pull_request",
        tenant_id=tenant_id,
        project_id=project_id,
        content_sha256=digest,
    )
    with pytest.raises(ApprovalRequired):
        require_approval(
            risk_class=RiskClass.HIGH,
            evidence=evidence,
            target="repo:acme/test:branch/main",
            operation="merge_pull_request",
            tenant_id=tenant_id,
            project_id=project_id,
            content_sha256=digest,
        )


def test_low_risk_does_not_require_approval_by_default() -> None:
    require_approval(
        risk_class=RiskClass.LOW,
        evidence=None,
        target="docs/report.md",
        operation="draft_documentation",
        tenant_id=uuid4(),
        project_id=uuid4(),
        content_sha256="b" * 64,
    )


def test_grants_reject_mutable_permission_sets() -> None:
    with pytest.raises(TypeError, match="immutable frozensets"):
        EffectiveGrant(uuid4(), uuid4(), {"repo.read"}, frozenset())


def test_approval_rejects_naive_expiry_and_invalid_digest() -> None:
    common = dict(
        approval_id=uuid4(), approved_by="reviewer", tenant_id=uuid4(), project_id=uuid4(),
        target="repo:test", operation="create_branch", risk_class=RiskClass.HIGH,
        content_sha256="a" * 64, status=ApprovalStatus.APPROVED,
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        ApprovalEvidence(**common, expires_at=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="SHA-256"):
        ApprovalEvidence(**(common | {"content_sha256": "not-a-digest"}),
                         expires_at=datetime.now(UTC) + timedelta(minutes=5))
