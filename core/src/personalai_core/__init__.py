"""PersonalAI core: orchestration, gateway, security engine, validation, registries.

Depends only on ``personalai_contracts`` (ADR-0001). Must not import the backend app or any
concrete adapter. M0-4 adds the registry/DI machinery: register adapters into :class:`Registries`
and resolve them by name at the composition root.
"""

from personalai_core.agent import AgentEvent, BlockedCall, ResumeFrame, run_agent
from personalai_core.config import CoreConfig, effective_config
from personalai_core.gateway import InProcessExecutor, RegisteredTool, ToolGateway
from personalai_core.graph import (
    AGENT_NAMES,
    DEFAULT_AGENT_PROMPTS,
    EGRESS_ALLOW_ALWAYS,
    EGRESS_ALLOW_ONCE,
    EGRESS_DENY,
    EGRESS_RESUME_DECISION,
    EGRESS_RESUME_FRAME,
    TOOL_CONFIGURABLE_AGENTS,
    TOOL_USING_AGENTS,
    GraphState,
    read_pending_interrupt,
    resolve_prompts,
    run_graph,
)
from personalai_core.memory import split_recent, summarize
from personalai_core.memory_consolidation import ConsolidationOutcome, consolidate_fact
from personalai_core.memory_extraction import extract_facts, recall, remember
from personalai_core.registries import Registries
from personalai_core.registry import Registry, RegistryError
from personalai_core.retrieval import VectorRetriever
from personalai_core.runaway import RepetitionWatchdog, RunawayConfig
from personalai_core.sources import (
    GraphSource,
    MemorySource,
    MergeResult,
    VectorSource,
    gather_sources,
    merge_evidence,
    plan_sources,
)
from personalai_core.structured import generate_structured

__version__ = "0.0.0"

__all__ = [
    "AGENT_NAMES",
    "DEFAULT_AGENT_PROMPTS",
    "EGRESS_ALLOW_ALWAYS",
    "EGRESS_ALLOW_ONCE",
    "EGRESS_DENY",
    "EGRESS_RESUME_DECISION",
    "EGRESS_RESUME_FRAME",
    "TOOL_USING_AGENTS",
    "TOOL_CONFIGURABLE_AGENTS",
    "AgentEvent",
    "BlockedCall",
    "ResumeFrame",
    "CoreConfig",
    "GraphState",
    "resolve_prompts",
    "InProcessExecutor",
    "ConsolidationOutcome",
    "RegisteredTool",
    "Registries",
    "Registry",
    "RegistryError",
    "RepetitionWatchdog",
    "RunawayConfig",
    "ToolGateway",
    "VectorRetriever",
    "GraphSource",
    "MemorySource",
    "MergeResult",
    "VectorSource",
    "gather_sources",
    "merge_evidence",
    "plan_sources",
    "__version__",
    "consolidate_fact",
    "effective_config",
    "extract_facts",
    "generate_structured",
    "read_pending_interrupt",
    "run_agent",
    "run_graph",
    "recall",
    "remember",
    "split_recent",
    "summarize",
]
