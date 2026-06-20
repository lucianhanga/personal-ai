"""Per-tenant preference settings (#289).

User-facing *preferences* that overlay the boot-time :class:`CoreConfig` per request. Every field
is optional: ``None`` means "inherit the deployment default" (the overlay only applies non-null
values). This contract deliberately excludes all server/boot/secret configuration -- AUTH_TOKEN,
DATABASE_URL, OPENAI_API_KEY, APP_MODE, bind host/port, CORS origins, sessions and the audit sink
stay environment-only and are never serialized to or from the settings API.

Field names match :class:`CoreConfig` exactly so the overlay is a plain ``model_copy(update=...)``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from personalai_contracts.schemas.base import StrictModel


class TenantSettings(StrictModel):
    """A tenant's preference overrides. All fields optional; ``None`` = inherit the default."""

    # --- Models ---
    model_provider: Literal["ollama", "openai_compat"] | None = None
    default_model: str | None = Field(default=None, min_length=1, max_length=200)
    ollama_host: str | None = Field(default=None, min_length=1, max_length=500)
    ollama_num_ctx: int | None = Field(default=None, ge=256, le=1_048_576)
    ollama_keep_alive: str | None = Field(default=None, min_length=1, max_length=32)
    embed_provider: Literal["ollama", "openai_compat"] | None = None
    embed_model: str | None = Field(default=None, min_length=1, max_length=200)
    openai_base_url: str | None = Field(default=None, min_length=1, max_length=500)

    # --- Agent (M8) ---
    # Agentic mode (#290): "single" = single-agent loop, "multi" = planner/researcher/critic graph,
    # "custom" = user-defined agents (reserved/future). Supersedes agent_graph_enabled as the
    # user-facing control; agent_graph_enabled is kept for backward-compatible env config.
    agent_mode: Literal["single", "multi", "custom"] | None = None
    agent_graph_enabled: bool | None = None
    agent_human_gate: bool | None = None
    agent_accuracy_mode: Literal["standard", "accurate"] | None = None
    agent_max_iterations: int | None = Field(default=None, ge=1, le=50)
    # Whole-turn wall-clock cap in seconds (E_TIMEOUT on expiry). 30s..1h.
    agent_timeout_seconds: int | None = Field(default=None, ge=30, le=3600)

    # --- Behaviour ---
    memory_enabled: bool | None = None
    grounding_enabled: bool | None = None
    max_upload_bytes: int | None = Field(default=None, ge=1, le=1_000_000_000)

    # --- Network egress (security-sensitive) ---
    # When egress_enabled is on, outbound calls from in-process tools are permitted only to hosts in
    # allowed_egress_hosts (empty = fail-closed, deny all). None on either inherits the deployment
    # default. Hosts are bare lowercase hostnames (no scheme/path).
    egress_enabled: bool | None = None
    allowed_egress_hosts: tuple[str, ...] | None = None
