"""The set of adapter registries, one per backend seam (ADR-0001).

Singleton-style seams (a config selects one active adapter): model providers, retrievers,
vector repositories, object stores, graph stores. Collection seams (many enabled at once):
modality handlers, agent roles, tools.

UI renderers are a frontend seam and are registered in the SPA (M0-6), not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from personalai_contracts.ports import (
    AgentRole,
    GraphStore,
    ModalityHandler,
    ModelProvider,
    ObjectStore,
    Retriever,
    VectorRepository,
)
from personalai_core.gateway import RegisteredTool
from personalai_core.registry import Registry


@dataclass
class Registries:
    """All adapter registries for the backend. Created empty; populated by the composition root."""

    model_providers: Registry[ModelProvider] = field(
        default_factory=lambda: Registry("model provider")
    )
    retrievers: Registry[Retriever] = field(default_factory=lambda: Registry("retriever"))
    vector_repositories: Registry[VectorRepository] = field(
        default_factory=lambda: Registry("vector repository")
    )
    object_stores: Registry[ObjectStore] = field(default_factory=lambda: Registry("object store"))
    graph_stores: Registry[GraphStore] = field(default_factory=lambda: Registry("graph store"))
    modality_handlers: Registry[ModalityHandler] = field(
        default_factory=lambda: Registry("modality handler")
    )
    agent_roles: Registry[AgentRole] = field(default_factory=lambda: Registry("agent role"))
    tools: Registry[RegisteredTool] = field(default_factory=lambda: Registry("tool"))
