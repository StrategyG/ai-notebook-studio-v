from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentHealth(StrEnum):
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    DISABLED = "DISABLED"


class ProtocolName(StrEnum):
    INTERNAL = "internal"
    A2A = "a2a"
    MCP = "mcp"


class ResourceLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_concurrency: int = Field(default=1, ge=1, le=128)
    max_task_seconds: int = Field(default=300, ge=1, le=86_400)
    max_delegation_depth: int = Field(default=0, ge=0, le=8)
    max_budget_usd: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=4)


class AgentDescriptor(BaseModel):
    """Platform-local registry entry; not an A2A AgentCard wire representation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str = Field(min_length=3, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]*$")
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=2_000)
    capabilities: frozenset[str] = Field(min_length=1, max_length=64)
    supported_task_types: frozenset[str] = Field(min_length=1, max_length=64)
    supported_protocols: frozenset[ProtocolName] = Field(default_factory=lambda: frozenset({ProtocolName.INTERNAL}))
    authentication_required: bool = True
    required_permissions: frozenset[str] = Field(default_factory=frozenset, max_length=128)
    resource_limits: ResourceLimits = Field(default_factory=ResourceLimits)
    health: AgentHealth = AgentHealth.OFFLINE
    tenant_id: UUID | None = None
    project_id: UUID | None = None
    registered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("capabilities", "supported_task_types", "required_permissions")
    @classmethod
    def validate_tokens(cls, values: frozenset[str]) -> frozenset[str]:
        for value in values:
            if not value or len(value) > 128 or any(ch.isspace() for ch in value):
                raise ValueError("registry values must be non-empty tokens without whitespace")
        return values

    @field_validator("registered_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("registered_at must be timezone-aware")
        return value

    @field_validator("project_id")
    @classmethod
    def project_requires_tenant(cls, value: UUID | None, info):
        if value is not None and info.data.get("tenant_id") is None:
            raise ValueError("project-scoped agents must also declare tenant_id")
        return value

    def is_eligible(
        self,
        *,
        capabilities: set[str],
        task_type: str,
        tenant_id: UUID,
        project_id: UUID,
    ) -> bool:
        if self.health != AgentHealth.AVAILABLE:
            return False
        if not capabilities.issubset(self.capabilities) or task_type not in self.supported_task_types:
            return False
        if self.tenant_id is not None and self.tenant_id != tenant_id:
            return False
        if self.project_id is not None and self.project_id != project_id:
            return False
        return True
