"""Ports: agent role and graph node.

An ``AgentNode`` is a single step in an orchestration graph (LangGraph-style): it maps an
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
    """Ambient context for an agent run (conversation, workspace, etc.)."""

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
