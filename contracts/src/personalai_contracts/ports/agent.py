"""Ports: agent role and graph node.

An ``AgentNode`` is a single step in an orchestration graph (a hand-rolled typed graph over the
existing seams — ADR-0011, M8; not LangGraph): it maps an
input state to an output state. An ``AgentRole`` is a named, described capability that
exposes such a node. Typed agent-message envelopes that flow as state are defined as schemas
in M0-3; orchestration wiring is M6.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# Agent state is an opaque, schema-validated mapping at this layer; M0-3 refines its shape.
AgentState = Mapping[str, Any]


@dataclass(frozen=True)
class AgentContext:
    """Context for an agent run. ``tenant_id``/``subject_id`` are REQUIRED so every node's data
    access is explicitly tenant-scoped (ADR-0010) rather than relying only on an ambient contextvar
    — important for M8 where multiple nodes/sub-tasks run within a turn (audit A2/#225)."""

    tenant_id: str
    subject_id: str
    conversation_id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class AgentNode(Protocol):
    """A single orchestration step: state in, state out."""

    name: str

    async def run(self, state: AgentState, context: AgentContext) -> AgentState:
        """Process ``state`` and return the next state."""
        ...


@runtime_checkable
class AgentRole(Protocol):
    """A named agent capability that exposes an orchestration node."""

    name: str
    description: str

    def node(self) -> AgentNode:
        """Return the orchestration node implementing this role."""
        ...
