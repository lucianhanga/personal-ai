"""Port: tool handler.

The execution contract for a tool or MCP server action. The full tool/MCP **manifest**
(provenance, permissions, I/O schemas, egress, risk, signature) is defined as a schema in
M0-3; permission enforcement and sandboxing live in the Tool/MCP gateway (M4). Tool handlers
are never invoked directly by agents — only through the gateway (ADR-0004).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ToolCall:
    """A validated request to invoke a tool. Mirrors the tool-invocation contract (M0-3)."""

    tool: str
    version: str
    args: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """The normalized result of a tool invocation (fail-closed: ok=False on error)."""

    ok: bool
    output: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None


@runtime_checkable
class ToolHandler(Protocol):
    """Executes a single tool/MCP action behind the gateway."""

    name: str

    async def invoke(self, call: ToolCall) -> ToolResult:
        """Execute ``call`` and return a normalized result."""
        ...


@runtime_checkable
class ToolExecutor(Protocol):
    """Runs a handler with a time bound. The seam that scales tool isolation: the in-process
    executor today; subprocess / container / remote-MCP executors later (M6+). Implementations
    must be fail-closed (return ``ToolResult(ok=False, ...)`` on timeout/error, never raise)."""

    async def execute(self, handler: ToolHandler, call: ToolCall, *, timeout: float) -> ToolResult:
        """Execute ``call`` via ``handler`` within ``timeout`` seconds."""
        ...
