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
    # Layered model stack (#491): per-task models beyond chat. ner_model is the Ollama model for
    # entity/relation extraction (KAG); rerank_enabled gates the post-retrieval cross-encoder rerank
    # (#492); rerank_model is its HF id. None on any inherits the deployment default (CoreConfig).
    ner_model: str | None = Field(default=None, min_length=1, max_length=200)
    rerank_enabled: bool | None = None
    rerank_model: str | None = Field(default=None, min_length=1, max_length=200)

    # --- Agent (M8) ---
    # Agentic mode (#290): "single" = single-agent loop, "multi" = planner/researcher/critic graph,
    # "custom" = user-defined agents (reserved/future). Supersedes agent_graph_enabled as the
    # user-facing control; agent_graph_enabled is kept for backward-compatible env config.
    agent_mode: Literal["single", "multi", "custom"] | None = None
    agent_graph_enabled: bool | None = None
    agent_human_gate: bool | None = None
    # Network-egress approval gate (#377), independent of the answer gate (agent_human_gate): pause
    # the turn to allow/deny a tool's call to a non-allowlisted host. None inherits the default.
    agent_egress_gate: bool | None = None
    agent_accuracy_mode: Literal["standard", "accurate"] | None = None
    # Judge fact-check (#465): when on, the final judge runs ONE bounded independent RAG/KAG
    # retrieval to fact-check the answer — the verifier in accurate mode, else the critic. None
    # inherits the deployment default.
    agent_verifier_check: bool | None = None
    # Tool-approval policy: require explicit per-turn approval of HIGH-risk tools before they run
    # (the composer's "approve tools" default follows this). None inherits the deployment default.
    tool_approval_required: bool | None = None
    agent_max_iterations: int | None = Field(default=None, ge=1, le=50)
    # Whole-turn wall-clock cap in seconds (E_TIMEOUT on expiry). 30s..1h.
    agent_timeout_seconds: int | None = Field(default=None, ge=30, le=3600)
    # Default reasoning ("how much to think") applied when a chat turn doesn't specify one — the
    # tenant-level default behind the per-agent reasoning overrides. None inherits the deployment
    # default (CoreConfig.default_reasoning).
    default_reasoning: Literal["off", "low", "medium", "high"] | None = None

    # --- Behaviour ---
    memory_enabled: bool | None = None
    grounding_enabled: bool | None = None
    # opt-in; lets the model emit Mermaid diagrams / rich markdown
    rich_output_enabled: bool | None = None
    max_upload_bytes: int | None = Field(default=None, ge=1, le=1_000_000_000)

    # --- Voice / speech-to-text (M9.2) ---
    # transcribe_base_url points at an OpenAI-compatible /v1 transcription endpoint (a local whisper
    # server, or OpenAI). The API key stays env-only (secret), like openai_api_key. None inherits.
    transcribe_enabled: bool | None = None
    transcribe_provider: Literal["local", "openai_compat"] | None = None
    transcribe_base_url: str | None = Field(default=None, min_length=1, max_length=500)
    transcribe_model: str | None = Field(default=None, min_length=1, max_length=200)
    # Spoken language: "auto" to detect, or an ISO-639-1 code (en/de/es/ro/...). Pinning avoids
    # Whisper mis-detecting the language on real-mic audio. None inherits the deployment default.
    transcribe_language: str | None = Field(default=None, min_length=2, max_length=10)

    # --- Voice / text-to-speech (M9.3) ---
    # Read assistant answers aloud (browser speech synthesis in slice 1). None inherits the default.
    tts_enabled: bool | None = None

    # --- Network egress (security-sensitive) ---
    # When egress_enabled is on, outbound calls from in-process tools are permitted only to hosts in
    # allowed_egress_hosts (empty = fail-closed, deny all). None on either inherits the deployment
    # default. Hosts are bare lowercase hostnames (no scheme/path).
    egress_enabled: bool | None = None
    allowed_egress_hosts: tuple[str, ...] | None = None
