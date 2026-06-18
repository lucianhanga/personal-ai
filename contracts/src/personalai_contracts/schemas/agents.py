"""Per-tenant multi-agent graph configuration (#290).

A tenant can override each graph agent's system prompt and disable specific tools/MCPs for it.
This is the *override* document only: an unset (``None``) prompt inherits the built-in default, and
``disabled_tools`` lists the tools the agent must NOT use (empty = all available tools allowed).
The default prompts and the available-tool roster live server-side and are echoed to the UI, so this
contract stays pure data with no defaults baked in (mirrors how ``TenantSettings`` carries only
overrides).
"""

from __future__ import annotations

from collections.abc import Mapping

from personalai_contracts.schemas.base import StrictModel


class AgentConfig(StrictModel):
    """One agent's overrides. ``name`` is a known graph agent (planner/researcher/critic)."""

    name: str
    prompt: str | None = None
    disabled_tools: tuple[str, ...] = ()


class AgentGraphConfig(StrictModel):
    """A tenant's overrides for the multi-agent graph; empty = all defaults."""

    agents: tuple[AgentConfig, ...] = ()

    def prompt_overrides(self) -> dict[str, str]:
        """Map of agent -> non-empty prompt override (skips inherited defaults)."""
        return {a.name: a.prompt for a in self.agents if a.prompt and a.prompt.strip()}

    def disabled_tools(self, agent: str) -> frozenset[str]:
        """Tool/MCP names this agent must not use (empty if the agent has no override)."""
        for a in self.agents:
            if a.name == agent:
                return frozenset(a.disabled_tools)
        return frozenset()

    @classmethod
    def from_map(cls, data: Mapping[str, Mapping[str, object]]) -> AgentGraphConfig:
        """Build from a ``{agent: {prompt, disabled_tools}}`` map (e.g. a stored JSON document)."""
        agents = tuple(
            AgentConfig(
                name=name,
                prompt=cfg.get("prompt"),  # type: ignore[arg-type]
                disabled_tools=tuple(cfg.get("disabled_tools", ()) or ()),  # type: ignore[arg-type]
            )
            for name, cfg in data.items()
        )
        return cls(agents=agents)
