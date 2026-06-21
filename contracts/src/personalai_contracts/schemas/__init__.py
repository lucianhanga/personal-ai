"""PersonalAI structured-output schemas (ADR-0003).

Strict, versioned Pydantic contracts plus the schema registry. JSON Schema (the canonical
interchange) is generated from these models into ``schemas/json/`` and shared with the TS/Zod
bindings under ``packages/contracts``.
"""

from personalai_contracts.schemas.agents import AgentConfig, AgentGraphConfig
from personalai_contracts.schemas.base import (
    SemVer,
    StrictModel,
    VersionedModel,
    parse_semver,
)
from personalai_contracts.schemas.memory import ExtractedFact, ExtractionResult
from personalai_contracts.schemas.messages import AgentMessage
from personalai_contracts.schemas.outputs import (
    ErrorInfo,
    RepairRequest,
    StructuredResult,
)
from personalai_contracts.schemas.registry import (
    SchemaError,
    SchemaRegistry,
    SchemaValidationError,
    default_registry,
)
from personalai_contracts.schemas.settings import TenantSettings
from personalai_contracts.schemas.tools import (
    Integrity,
    Permission,
    PermissionType,
    Provenance,
    RiskLevel,
    ToolInvocation,
    ToolManifest,
)
from personalai_contracts.schemas.verdict import Verdict

__all__ = [
    # agents
    "AgentConfig",
    "AgentGraphConfig",
    # base
    "SemVer",
    "StrictModel",
    "VersionedModel",
    "parse_semver",
    # messages
    "AgentMessage",
    # memory extraction
    "ExtractedFact",
    "ExtractionResult",
    # outputs
    "ErrorInfo",
    "RepairRequest",
    "StructuredResult",
    # registry
    "SchemaError",
    "SchemaRegistry",
    "SchemaValidationError",
    "default_registry",
    # settings
    "TenantSettings",
    "Verdict",
    # tools
    "Integrity",
    "Permission",
    "PermissionType",
    "Provenance",
    "RiskLevel",
    "ToolInvocation",
    "ToolManifest",
]
