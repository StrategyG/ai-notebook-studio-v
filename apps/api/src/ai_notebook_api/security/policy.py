from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from ai_notebook_api.domain.task_contract import RiskClass


class AuthorizationDenied(PermissionError):
    pass


class ApprovalRequired(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class EffectiveGrant:
    tenant_id: UUID
    project_id: UUID
    actions: frozenset[str]
    capabilities: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.actions, frozenset) or not isinstance(self.capabilities, frozenset):
            raise TypeError("grant actions and capabilities must be immutable frozensets")
        for item in self.actions | self.capabilities:
            if not item or len(item) > 128 or any(ch.isspace() for ch in item):
                raise ValueError("grant values must be non-empty tokens without whitespace")


def intersect_grants(*grants: EffectiveGrant) -> EffectiveGrant:
    if not grants:
        raise ValueError("at least one grant is required")
    tenant_ids = {grant.tenant_id for grant in grants}
    project_ids = {grant.project_id for grant in grants}
    if len(tenant_ids) != 1 or len(project_ids) != 1:
        raise AuthorizationDenied("grant scopes do not refer to the same tenant and project")
    actions = set(grants[0].actions)
    capabilities = set(grants[0].capabilities)
    for grant in grants[1:]:
        actions.intersection_update(grant.actions)
        capabilities.intersection_update(grant.capabilities)
    return EffectiveGrant(
        tenant_id=grants[0].tenant_id,
        project_id=grants[0].project_id,
        actions=frozenset(actions),
        capabilities=frozenset(capabilities),
    )


def authorize_delegation(
    *, effective_grant: EffectiveGrant, requested_actions: set[str], requested_capabilities: set[str]
) -> None:
    if not requested_actions.issubset(effective_grant.actions):
        raise AuthorizationDenied("delegated task requests actions outside the effective grant")
    if not requested_capabilities.issubset(effective_grant.capabilities):
        raise AuthorizationDenied("delegated task requests capabilities outside the effective grant")


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class ApprovalEvidence:
    approval_id: UUID
    approved_by: str
    tenant_id: UUID
    project_id: UUID
    target: str
    operation: str
    risk_class: RiskClass
    content_sha256: str
    expires_at: datetime
    status: ApprovalStatus

    def __post_init__(self) -> None:
        if not self.approved_by.strip() or not self.target.strip() or not self.operation.strip():
            raise ValueError("approval actor, target and operation are required")
        if not re.fullmatch(r"[a-f0-9]{64}", self.content_sha256):
            raise ValueError("approval content_sha256 must be a lowercase SHA-256 digest")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("approval expiry must be timezone-aware")

    def matches(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        target: str,
        operation: str,
        risk_class: RiskClass,
        content_sha256: str,
        now: datetime | None = None,
    ) -> bool:
        now = now or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("approval comparison time must be timezone-aware")
        return (
            self.status == ApprovalStatus.APPROVED
            and self.expires_at > now
            and self.tenant_id == tenant_id
            and self.project_id == project_id
            and self.target == target
            and self.operation == operation
            and self.risk_class == risk_class
            and self.content_sha256 == content_sha256
        )


def require_approval(
    *, risk_class: RiskClass, evidence: ApprovalEvidence | None, target: str,
    operation: str, tenant_id: UUID, project_id: UUID, content_sha256: str
) -> None:
    if risk_class not in {RiskClass.HIGH, RiskClass.CRITICAL}:
        return
    if evidence is None or not evidence.matches(
        tenant_id=tenant_id,
        project_id=project_id,
        target=target,
        operation=operation,
        risk_class=risk_class,
        content_sha256=content_sha256,
    ):
        raise ApprovalRequired("a current approval bound to this exact action and content is required")
