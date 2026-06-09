"""Tool invocation contract and tool/MCP manifest (ADR-0003, ADR-0004).

- ``ToolInvocation`` is the validated request an agent emits to call a tool; it is checked and
  authorized by the Tool/MCP gateway before any execution (M4).
- ``ToolManifest`` is what every tool/MCP server declares about itself: provenance, version,
  capabilities, least-privilege permissions, I/O JSON Schemas, allowed network egress (deny by
  default), risk level (defaults to HIGH for unverified tools), and integrity for pinning.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import Field

from personalai_contracts.schemas.base import StrictModel, VersionedModel


class PermissionType(StrEnum):
    """The class of capability a permission grants."""

    FILESYSTEM = "filesystem"
    NETWORK = "network"
    EXEC = "exec"
    ENV = "env"
    CLIPBOARD = "clipboard"


class RiskLevel(StrEnum):
    """Declared risk of a tool. Unverified tools default to HIGH."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Permission(StrictModel):
    """A single least-privilege grant, e.g. filesystem access to a path glob."""

    type: PermissionType
    scope: str = Field(description="What the grant applies to (path glob, host, var name, ...).")


class Provenance(StrictModel):
    """Who made the tool and where it comes from (verified-provenance policy)."""

    maintainer: str
    repository: str | None = None
    license: str | None = None


class Integrity(StrictModel):
    """Integrity reference used to pin a tool/MCP to an exact artifact."""

    algorithm: str = Field(description="e.g. 'sha256'.")
    value: str


class ToolInvocation(VersionedModel):
    """A validated request to invoke a tool (mirrors the ToolCall port value object)."""

    SCHEMA_ID: ClassVar[str] = "personalai.tool.invocation"
    SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    tool: str
    version: str
    args: Mapping[str, Any] = Field(default_factory=dict)
    required_permissions: Sequence[Permission] = Field(default_factory=tuple)
    schema_version: str = Field(default=SCHEMA_VERSION)


class ToolManifest(VersionedModel):
    """The self-declaration every tool/MCP server must provide before it can be enabled."""

    SCHEMA_ID: ClassVar[str] = "personalai.tool.manifest"
    SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    name: str
    version: str
    provenance: Provenance
    description: str = Field(default="", description="What the tool does (shown to the model).")
    capabilities: Sequence[str] = Field(default_factory=tuple)
    permissions: Sequence[Permission] = Field(
        default_factory=tuple, description="Least-privilege; empty means no special access."
    )
    inputs: Mapping[str, Any] = Field(default_factory=dict, description="JSON Schema of inputs.")
    outputs: Mapping[str, Any] = Field(default_factory=dict, description="JSON Schema of outputs.")
    egress: Sequence[str] = Field(
        default_factory=tuple, description="Allowed network hosts; empty means no egress (deny)."
    )
    risk: RiskLevel = Field(default=RiskLevel.HIGH)
    integrity: Integrity | None = None
    schema_version: str = Field(default=SCHEMA_VERSION)
