"""PersonalAI core: orchestration, gateway, security engine, validation, registries.

Depends only on ``personalai_contracts`` (ADR-0001). Must not import the backend app or any
concrete adapter. M0-4 adds the registry/DI machinery: register adapters into :class:`Registries`
and resolve them by name at the composition root.
"""

from personalai_core.agent import AgentEvent, run_agent
from personalai_core.config import CoreConfig
from personalai_core.gateway import InProcessExecutor, RegisteredTool, ToolGateway
from personalai_core.graph import GraphState, run_graph
from personalai_core.memory import split_recent, summarize
from personalai_core.memory_extraction import extract_facts, recall, remember
from personalai_core.registries import Registries
from personalai_core.registry import Registry, RegistryError
from personalai_core.retrieval import VectorRetriever

__version__ = "0.0.0"

__all__ = [
    "AgentEvent",
    "CoreConfig",
    "GraphState",
    "InProcessExecutor",
    "RegisteredTool",
    "Registries",
    "Registry",
    "RegistryError",
    "ToolGateway",
    "VectorRetriever",
    "__version__",
    "extract_facts",
    "run_agent",
    "run_graph",
    "recall",
    "remember",
    "split_recent",
    "summarize",
]
