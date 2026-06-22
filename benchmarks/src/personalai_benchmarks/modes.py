"""Benchmark modes: named sets of per-run overrides sent to /assistant/execute.

Each mode carries a ``capability_tier`` so the leaderboard groups like-with-like and never averages
a tool-equipped agent against a raw model. Add a new mode here (no framework changes needed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Mode:
    """A benchmark configuration: a capability tier + the execute overrides that realize it."""

    name: str
    capability_tier: str
    overrides: dict[str, Any] = field(default_factory=dict)


def with_memory(mode: Mode) -> Mode:
    """A memory-on variant of ``mode``: reads long-term memory into the turn (``use_memory``) and
    enables the memory write/extraction path (``memory_enabled``). Memory is a benchmark dimension —
    the variant gets its own capability tier so on/off results are never averaged together."""
    return Mode(
        name=f"{mode.name}_memory",
        capability_tier=f"{mode.capability_tier}+memory",
        overrides={**mode.overrides, "use_memory": True, "memory_enabled": True},
    )


# Phase 1 modes. Memory off by default; `with_memory(...)` adds the on variant. Reasoning settings
# can be swept the same way (add variants with reasoning="full").
SINGLE_NO_TOOLS = Mode(
    name="single_no_tools",
    capability_tier="single_no_tools",
    overrides={"agent_mode": "single", "use_tools": False, "use_mcp": False, "use_memory": False},
)
SINGLE_TOOLS_MCP = Mode(
    name="single_tools_mcp",
    capability_tier="single_tools",
    overrides={"agent_mode": "single", "use_tools": True, "use_mcp": True, "use_memory": False},
)
MULTI_TOOLS_MCP = Mode(
    name="multi_tools_mcp",
    capability_tier="multi_agent",
    overrides={"agent_mode": "multi", "use_tools": True, "use_mcp": True, "use_memory": False},
)

ALL_MODES: dict[str, Mode] = {
    m.name: m
    for m in (
        SINGLE_NO_TOOLS,
        SINGLE_TOOLS_MCP,
        MULTI_TOOLS_MCP,
        # Memory on/off as a sweepable axis (the tool/agent modes can actually use recalled memory).
        with_memory(SINGLE_TOOLS_MCP),
        with_memory(MULTI_TOOLS_MCP),
    )
}
