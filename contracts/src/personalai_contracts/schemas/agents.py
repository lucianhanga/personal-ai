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
    """One agent's overrides. ``name`` is a known graph agent (planner/researcher/critic).

    ``reasoning`` is the per-agent thinking budget: "off"/"low"/"medium"/"high" (None inherits the
    agent's built-in default). It maps to the model's thinking switch + a graded reasoning-budget
    nudge in the graph nodes — the same mechanism the single-agent chat path uses.

    ``model`` overrides the model this agent runs on (None inherits the turn's model), so e.g. the
    planner can run on a small fast model while the researcher uses a larger one.
    """

    name: str
    prompt: str | None = None
    disabled_tools: tuple[str, ...] = ()
    reasoning: str | None = None
    model: str | None = None


class AgentGraphConfig(StrictModel):
    """A tenant's overrides for the multi-agent graph; empty = all defaults."""

    agents: tuple[AgentConfig, ...] = ()

    def prompt_overrides(self) -> dict[str, str]:
        """Map of agent -> non-empty prompt override (skips inherited defaults)."""
        return {a.name: a.prompt for a in self.agents if a.prompt and a.prompt.strip()}

    def reasoning_levels(self) -> dict[str, str]:
        """Map of agent -> reasoning level override (skips agents with no level set)."""
        return {a.name: a.reasoning for a in self.agents if a.reasoning}

    def model_overrides(self) -> dict[str, str]:
        """Map of agent -> model override (skips agents with no model set)."""
        return {a.name: a.model for a in self.agents if a.model and a.model.strip()}

    def disabled_tools(self, agent: str) -> frozenset[str]:
        """Tool/MCP names this agent must not use (empty if the agent has no override)."""
        for a in self.agents:
            if a.name == agent:
                return frozenset(a.disabled_tools)
        return frozenset()

    @classmethod
    def from_map(cls, data: Mapping[str, Mapping[str, object]]) -> AgentGraphConfig:
        """Build from a stored ``{agent: {prompt, disabled_tools, reasoning, model}}`` JSON map."""
        agents = tuple(
            AgentConfig(
                name=name,
                prompt=cfg.get("prompt"),  # type: ignore[arg-type]
                disabled_tools=tuple(cfg.get("disabled_tools", ()) or ()),  # type: ignore[arg-type]
                reasoning=cfg.get("reasoning"),  # type: ignore[arg-type]
                model=cfg.get("model"),  # type: ignore[arg-type]
            )
            for name, cfg in data.items()
        )
        return cls(agents=agents)
