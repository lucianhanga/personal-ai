"""Core configuration: which adapters are active, and runtime safety defaults.

Config-driven selection (ADR-0001): the composition root reads :class:`CoreConfig` and resolves
the active singleton adapters from the registries. Security defaults are local-first: bind to
loopback, keep network egress disabled, and only accept requests from allow-listed browser
origins unless explicitly widened (ADR / THREAT-MODEL). Proper secrets handling arrives in M0-10.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import Field

from personalai_contracts.schemas import TenantSettings
from personalai_contracts.schemas.base import StrictModel
from personalai_core.runaway import RunawayConfig

_ENV_PREFIX = "PERSONALAI_"

# Maps an env var (without prefix) to a CoreConfig field.
_ENV_FIELDS = {
    "APP_MODE": "app_mode",
    "MODEL_PROVIDER": "model_provider",
    "DEFAULT_MODEL": "default_model",
    "NER_MODEL": "ner_model",
    "NER_NUM_CTX": "ner_num_ctx",
    "NER_MEMORY_FRACTION": "ner_memory_fraction",
    "OLLAMA_HOST": "ollama_host",
    "OLLAMA_NUM_CTX": "ollama_num_ctx",
    "OLLAMA_KEEP_ALIVE": "ollama_keep_alive",
    "OLLAMA_TIMEOUT": "ollama_timeout",
    "OLLAMA_TEMPERATURE": "ollama_temperature",
    "OLLAMA_TOP_P": "ollama_top_p",
    "OLLAMA_TOP_K": "ollama_top_k",
    "OLLAMA_REPEAT_PENALTY": "ollama_repeat_penalty",
    "OLLAMA_REPEAT_LAST_N": "ollama_repeat_last_n",
    "OPENAI_FREQUENCY_PENALTY": "openai_frequency_penalty",
    "OPENAI_PRESENCE_PENALTY": "openai_presence_penalty",
    "MAX_OUTPUT_TOKENS": "max_output_tokens",
    "RUNAWAY_GUARD_ENABLED": "runaway_guard_enabled",
    "RUNAWAY_MIN_LINE_CHARS": "runaway_min_line_chars",
    "RUNAWAY_LINE_REPEAT_THRESHOLD": "runaway_line_repeat_threshold",
    "RUNAWAY_LINE_WINDOW": "runaway_line_window",
    "RUNAWAY_NGRAM_SIZE": "runaway_ngram_size",
    "RUNAWAY_NGRAM_REPEAT_THRESHOLD": "runaway_ngram_repeat_threshold",
    "RUNAWAY_NGRAM_COVERAGE": "runaway_ngram_coverage",
    "RUNAWAY_WORD_WINDOW": "runaway_word_window",
    "MCP_CONFIG": "mcp_config_path",
    "AGENT_MAX_ITERATIONS": "agent_max_iterations",
    "AGENT_TIMEOUT_SECONDS": "agent_timeout_seconds",
    "AGENT_MODE": "agent_mode",
    "AGENT_GRAPH_ENABLED": "agent_graph_enabled",
    "AGENT_HUMAN_GATE": "agent_human_gate",
    "AGENT_ACCURACY_MODE": "agent_accuracy_mode",
    "AGENT_VERIFIER_CHECK": "agent_verifier_check",
    "RETRIEVER": "retriever",
    "VECTOR_REPOSITORY": "vector_repository",
    "OBJECT_STORE": "object_store",
    "BIND_HOST": "bind_host",
    "BIND_PORT": "bind_port",
    "EGRESS_ENABLED": "egress_enabled",
    "ALLOWED_EGRESS_HOSTS": "allowed_egress_hosts",
    "EGRESS_ALLOW_ANY": "egress_allow_any",
    "AUTH_TOKEN": "auth_token",
    "ALLOWED_ORIGINS": "allowed_origins",
    "OPENAI_API_KEY": "openai_api_key",  # pragma: allowlist secret  (env var name, not a secret)
    "OPENAI_BASE_URL": "openai_base_url",
    "TRANSCRIBE_ENABLED": "transcribe_enabled",
    "TRANSCRIBE_PROVIDER": "transcribe_provider",
    "TRANSCRIBE_MODEL": "transcribe_model",
    "TRANSCRIBE_LANGUAGE": "transcribe_language",
    "TRANSCRIBE_BASE_URL": "transcribe_base_url",
    "TRANSCRIBE_API_KEY": "transcribe_api_key",  # pragma: allowlist secret  (env var name)
    "TTS_ENABLED": "tts_enabled",
    "WEB_SEARCH_PROVIDER": "web_search_provider",
    "WEB_SEARCH_BASE_URL": "web_search_base_url",
    "WEB_SEARCH_API_KEY": "web_search_api_key",  # pragma: allowlist secret  (env var name)
    "WEB_SEARCH_MAX_RESULTS": "web_search_max_results",
    "DATABASE_URL": "database_url",
    "DB_POOL_MAX_SIZE": "db_pool_max_size",
    "EMBED_PROVIDER": "embed_provider",
    "EMBED_MODEL": "embed_model",
    "MAX_UPLOAD_BYTES": "max_upload_bytes",
    "MAX_REQUEST_BYTES": "max_request_bytes",
    "STM_KEEP_RECENT": "stm_keep_recent",
    "STM_SUMMARIZE": "stm_summarize",
    "MEMORY_ENABLED": "memory_enabled",
    "MEMORY_TOP_K": "memory_top_k",
    "GROUNDING_ENABLED": "grounding_enabled",
    "AUDIT_LOG_PATH": "audit_log_path",
    "SESSION_IDLE_SECONDS": "session_idle_seconds",
    "SESSION_ABSOLUTE_SECONDS": "session_absolute_seconds",
}

_INT_FIELDS = {
    "bind_port",
    "max_upload_bytes",
    "max_request_bytes",
    "db_pool_max_size",
    "stm_keep_recent",
    "memory_top_k",
    "ner_num_ctx",
    "ollama_num_ctx",
    "ollama_top_k",
    "ollama_repeat_last_n",
    "max_output_tokens",
    "runaway_min_line_chars",
    "runaway_line_repeat_threshold",
    "runaway_line_window",
    "runaway_ngram_size",
    "runaway_ngram_repeat_threshold",
    "runaway_word_window",
    "agent_max_iterations",
    "agent_timeout_seconds",
    "session_idle_seconds",
    "session_absolute_seconds",
    "web_search_max_results",
}
_FLOAT_FIELDS = {
    "ner_memory_fraction",
    "ollama_timeout",
    "ollama_temperature",
    "ollama_top_p",
    "ollama_repeat_penalty",
    "openai_frequency_penalty",
    "openai_presence_penalty",
    "runaway_ngram_coverage",
}
_BOOL_FIELDS = {
    "egress_enabled",
    "stm_summarize",
    "memory_enabled",
    "egress_allow_any",
    "grounding_enabled",
    "agent_graph_enabled",
    "agent_human_gate",
    "agent_verifier_check",
    "transcribe_enabled",
    "tts_enabled",
    "runaway_guard_enabled",
}

_CSV_FIELDS = {"allowed_origins", "allowed_egress_hosts"}

_TRUTHY = {"1", "true", "yes", "on"}
_DEFAULT_ORIGINS = (
    "http://127.0.0.1",
    "http://localhost",
    # Vite dev (5173) and preview (4173) servers, loopback only — for local UI development.
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
)


class CoreConfig(StrictModel):
    """Selection of active adapters plus local-first runtime defaults."""

    # Deployment mode (ADR-0010): "local" = single-user dev/personal (dev-login, stdio MCP ok);
    # "hosted" = multi-tenant SaaS (real login required, cookies+CSRF, remote-HTTP MCP only).
    app_mode: str = "local"
    model_provider: str = "ollama"
    default_model: str = "qwen3.6:35b-a3b"
    # NER/KAG runs on its OWN small, fast model (not the heavy chat model) with a small context, so
    # entity extraction is cheap and fits in memory alongside the chat model (#464). A dedicated
    # loopback Ollama runner is built for it; it must stay local (fail-closed, no egress).
    ner_model: str = "qwen3:14b"
    ner_num_ctx: int = 8192
    # Admission budget: the NER loader will only load its model if it fits within this fraction of
    # total system memory (measured against the GLOBAL Ollama load), else it defers. 0.75 matches
    # Apple Silicon's Metal working-set default; tune down on a busy shared box.
    ner_memory_fraction: float = 0.75
    ollama_host: str = "http://127.0.0.1:11434"
    # Bound the Ollama context window (KV cache) to control memory / avoid swap on constrained RAM.
    ollama_num_ctx: int = 32768
    # How long Ollama keeps the model resident after a request ("30m", "1h", "-1" = never unload).
    # Keeps a large model warm between turns so it isn't cold-reloaded (slow on big models).
    ollama_keep_alive: str = "30m"
    # HTTP client timeout (seconds) for the Ollama API. Generous by default: a COLD load of a large
    # model (e.g. the 35B MoE default) can take well over 120s to return its first token on a shared
    # GPU, which used to surface as httpx.ReadTimeout and silently drop best-effort NER. Streaming
    # resets the read clock per chunk, so this mainly bounds time-to-first-token.
    ollama_timeout: float = 600.0
    # Default sampling sent to Ollama when a request doesn't override it. Tuned for grounded agent
    # work on Qwen3 (its docs: temp 0.7 / top_p 0.8 / top_k 20 for non-thinking; greedy temp 0 is
    # discouraged). Lower top_p than the model's 0.95 default keeps it closer to retrieved context.
    ollama_temperature: float = 0.7
    ollama_top_p: float = 0.8
    ollama_top_k: int = 20
    # Repetition penalties (Layer 1 of the runaway-generation guard, #414): make the sampler less
    # likely to fall into verbatim loops. Conservative defaults — do NOT raise repeat_penalty above
    # ~1.2 by default (1.3-1.5 strongly suppresses but distorts prose, and breaks variable reuse in
    # code). repeat_last_n is the look-back window the penalty applies over. These REDUCE but do not
    # ELIMINATE loops, hence the hard output cap (max_output_tokens) and the streaming watchdog.
    ollama_repeat_penalty: float = 1.1
    ollama_repeat_last_n: int = 64
    # OpenAI-compatible equivalent of the repeat penalties (range -2..2; 0.1-1.0 is the "reduce
    # somewhat" band, >1 degrades quality). frequency_penalty scales with how often a token already
    # appeared; presence_penalty is a flat penalty for any reuse (left at 0 by default).
    openai_frequency_penalty: float = 0.3
    openai_presence_penalty: float = 0.0
    # Hard per-turn output ceiling (Layer 2 of the runaway guard, #414): the default num_predict /
    # max_tokens applied to every generation that carries no explicit max_tokens, so a single agent
    # turn cannot run unbounded until the wall-clock timeout. Generous for a normal answer, fatal to
    # an unbounded loop. An explicit smaller per-request max_tokens still wins. A length-capped
    # finish surfaces as finish_reason == "length" so the UI frames it as truncation, not a hang.
    max_output_tokens: int = 4096
    # Streaming repetition watchdog (Layer 3 — the PRIMARY fix, #414). A server-side detector over
    # streamed deltas that ABORTS a generation degenerating into verbatim repetition (the incident:
    # the same reasoning line repeated hundreds of times, under any token cap). Default ON. The
    # thresholds are conservative so legitimate short lists / repeated code idioms do NOT trip; they
    # are config-tunable so they can be loosened without a deploy.
    runaway_guard_enabled: bool = True
    # A line must be at least this many chars (after trimming) before repeats of it count — keeps
    # legitimate blank lines / short list items from tripping the detector.
    runaway_min_line_chars: int = 12
    # Trip when the SAME normalized line repeats this many times within the recent line window.
    runaway_line_repeat_threshold: int = 6
    runaway_line_window: int = 80
    # Trip when a word n-gram of this length repeats runaway_ngram_repeat_threshold times within the
    # recent word window (catches near-identical loops that are not line-delimited).
    runaway_ngram_size: int = 8
    runaway_ngram_repeat_threshold: int = 24
    # A repeating n-gram must also cover at least this fraction of the recent word window to trip —
    # separates a tight verbatim loop from frequent-but-legitimate phrase reuse (numbered steps,
    # boilerplate). See RunawayConfig.ngram_coverage.
    runaway_ngram_coverage: float = 0.5
    runaway_word_window: int = 400
    # Path to an mcp.json (mcpServers map) of MCP servers to connect at startup (M7); empty = none.
    mcp_config_path: str = ""
    # Max model<->tool iterations in the agent loop before it must answer (multi-step tool use).
    agent_max_iterations: int = 8
    # Hard wall-clock cap on a whole chat turn (seconds). A wedged model/node can't hang the turn
    # forever; on expiry the stream emits E_TIMEOUT. Generous default for big local models.
    agent_timeout_seconds: int = 300
    # M8 (ADR-0011): opt into the multi-agent typed graph (planner/researcher/critic/verifier);
    # default off keeps the single-agent loop. accuracy_mode drives the verification-ladder depth
    # ("standard"/"accurate"). Security gates (approval, egress, tenant) are NEVER accuracy-gated.
    agent_graph_enabled: bool = False
    # Agentic mode (#290): "single" = single-agent loop, "multi" = the planner/researcher/critic
    # graph, "custom" = user-defined agents (reserved/future). The user-facing control; the chat
    # path drives graph selection off this. agent_graph_enabled stays as the legacy env flag
    # (from_env upgrades the mode to "multi" when it is set and no mode is given).
    agent_mode: str = "single"
    # M8.1c (ADR-0012): when the graph is enabled, also suspend each turn at a durable human gate
    # (after the critic) for approve/reject before finalizing. Requires the graph; default off so
    # the normal flow finalizes without a gate. The checkpoint is tenant-scoped (RLS) via TenantDb.
    agent_human_gate: bool = False
    agent_accuracy_mode: str = "standard"
    # Tool-armed verifier (#465): in accurate mode, let the verifier do ONE bounded INDEPENDENT
    # retrieval (re-query RAG/KAG/memory) to fact-check the draft's claims, not just judge it
    # against the researcher's own sources. Fail-open + conservative. Toggleable in Settings.
    agent_verifier_check: bool = True
    retriever: str = "pgvector"
    vector_repository: str = "pgvector"
    object_store: str = "local"
    # Dev default: local pgvector via docker-compose (trust auth, no password in code).
    database_url: str = "postgresql://personalai@127.0.0.1:5432/personalai"
    # asyncpg pool max size. A turn fans out into per-node RLS-bound queries (each a short
    # transaction) concurrent with streaming + background memory, and M8 multiplies that — so the
    # default is generous to avoid pool-exhaustion stalls.
    db_pool_max_size: int = 20
    embed_provider: str = "ollama"
    embed_model: str = "qwen3-embedding:0.6b"
    max_upload_bytes: int = 10_000_000
    # Hard ceiling on any request body (DoS guard); exceeds max_upload_bytes + multipart overhead.
    max_request_bytes: int = 12_000_000
    # Short-term memory: keep the last N messages verbatim; fold older turns into a rolling summary.
    stm_keep_recent: int = 10
    stm_summarize: bool = True
    # Long-term memory: extract durable facts after a turn (skipped for incognito conversations).
    memory_enabled: bool = True
    memory_top_k: int = 5
    # Multi-source retrieval (#420): the cross-source evidence token budget the merge node fits
    # the fused vector+memory[+...] evidence to (the first real token budget; a conservative slice
    # of the 32k window after date/grounding/STM, with a per-source floor). 0 disables trimming.
    evidence_budget: int = 6000
    # Inject a grounding/anti-hallucination system prompt (ground in context/tools; admit doubt).
    grounding_enabled: bool = True
    # Append-only JSONL audit sink path (survives restart); empty = in-memory only.
    audit_log_path: str = ""
    # Session lifetimes (ADR-0010): sliding idle window + hard absolute cap, in seconds.
    session_idle_seconds: int = 86_400  # 24h
    session_absolute_seconds: int = 604_800  # 7d
    bind_host: str = Field(default="127.0.0.1", description="Loopback by default.")
    bind_port: int = Field(default=8765, ge=1, le=65535)
    egress_enabled: bool = Field(default=False, description="Network egress off by default.")
    allowed_egress_hosts: tuple[str, ...] = Field(
        default=(),
        description="When egress is enabled, the hosts allowed. Empty = fail-closed (deny all).",
    )
    egress_allow_any: bool = Field(
        default=False,
        description="Explicit opt-in to allow ANY host when egress is enabled with no allowlist.",
    )
    auth_token: str | None = Field(
        default=None, description="Bearer token required by protected routes; set via env."
    )
    allowed_origins: tuple[str, ...] = Field(
        default=_DEFAULT_ORIGINS, description="Browser origins permitted to call the API."
    )
    openai_api_key: str | None = Field(
        default=None, description="API key for the OpenAI-compatible remote provider (secret)."
    )
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="Base URL for the OpenAI-compatible remote provider.",
    )
    # Speech-to-text (M9.2): opt-in voice input via an OpenAI-compatible /audio/transcriptions
    # endpoint (OpenAI or a local whisper server). Off by default; a local server on loopback works
    # with egress disabled. Empty base/key fall back to the OpenAI provider's base/key.
    transcribe_enabled: bool = Field(default=True, description="Enable speech-to-text input.")
    # "local" = in-process faster-whisper (zero-setup, multilingual; downloads the model once);
    # "openai_compat" = a remote/local whisper SERVER over /v1/audio/transcriptions.
    transcribe_provider: str = Field(default="local", description="local | openai_compat")
    transcribe_model: str = Field(
        default="large-v3-turbo", description="Transcription model (faster-whisper size or OpenAI)."
    )
    # "auto" = auto-detect the spoken language (multilingual). Whisper's auto-detection is
    # probabilistic and can pick the wrong language on real-mic audio (accent/noise/codec), so a
    # specific ISO-639-1 code (en/de/es/ro/...) can be pinned to force it.
    transcribe_language: str = Field(
        default="auto", description='Spoken language: "auto" to detect, or an ISO-639-1 code.'
    )
    transcribe_base_url: str = Field(
        default="", description="Transcription endpoint base URL; empty = use openai_base_url."
    )
    transcribe_api_key: str | None = Field(
        default=None, description="Transcription API key (secret); empty = use openai_api_key."
    )
    # Text-to-speech (M9.3): read assistant answers aloud. Slice 1 uses the browser's built-in
    # speech synthesis (client-side, zero-setup); this flag just gates the read-aloud control.
    tts_enabled: bool = Field(default=True, description="Enable reading answers aloud (TTS).")
    # Web search provider (#395): the built-in web_search tool's backend.
    #   "duckduckgo" = zero-setup HTML scrape, no key, egress html.duckduckgo.com (the default, so
    #     existing users are unaffected);
    #   "searxng" = a self-hosted SearXNG JSON instance (needs web_search_base_url; local-first —
    #     a loopback instance works with egress disabled);
    #   "tavily" = the Tavily search API (needs web_search_api_key + egress api.tavily.com).
    # A provider whose required setting is missing falls back to DuckDuckGo (logged), never crashes.
    web_search_provider: str = Field(
        default="duckduckgo", description="duckduckgo | searxng | tavily"
    )
    web_search_base_url: str | None = Field(
        default=None, description="SearXNG instance base URL (e.g. http://127.0.0.1:8888)."
    )
    web_search_api_key: str | None = Field(
        default=None, description="Tavily API key (secret); required for the tavily provider."
    )
    web_search_max_results: int = Field(
        default=5, description="Default number of web_search results (the tool caps it at 10)."
    )

    def runaway_config(self) -> RunawayConfig:
        """Assemble the streaming repetition watchdog's thresholds (#414) from this config, so the
        agent loop can build a :class:`RepetitionWatchdog` per turn without reaching into fields."""
        return RunawayConfig(
            enabled=self.runaway_guard_enabled,
            min_line_chars=self.runaway_min_line_chars,
            line_repeat_threshold=self.runaway_line_repeat_threshold,
            line_window=self.runaway_line_window,
            ngram_size=self.runaway_ngram_size,
            ngram_repeat_threshold=self.runaway_ngram_repeat_threshold,
            ngram_coverage=self.runaway_ngram_coverage,
            word_window=self.runaway_word_window,
        )

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> CoreConfig:
        """Build config from ``PERSONALAI_*`` environment variables, falling back to defaults."""
        values: dict[str, object] = {}
        for env_key, field_name in _ENV_FIELDS.items():
            raw = environ.get(_ENV_PREFIX + env_key)
            if raw is None:
                continue
            if field_name in _BOOL_FIELDS:
                values[field_name] = raw.strip().lower() in _TRUTHY
            elif field_name in _INT_FIELDS:
                values[field_name] = int(raw)
            elif field_name in _FLOAT_FIELDS:
                values[field_name] = float(raw)
            elif field_name in _CSV_FIELDS:
                values[field_name] = tuple(o.strip() for o in raw.split(",") if o.strip())
            else:
                values[field_name] = raw
        # Back-compat (#290): the legacy AGENT_GRAPH_ENABLED flag maps to agent_mode="multi" when no
        # explicit AGENT_MODE is given, so existing env config keeps selecting the graph.
        if "agent_mode" not in values and values.get("agent_graph_enabled") is True:
            values["agent_mode"] = "multi"
        return cls.model_validate(values)


def effective_config(base: CoreConfig, overrides: TenantSettings) -> CoreConfig:
    """Overlay a tenant's non-null preference overrides (#289) onto the boot-time ``base`` config.

    ``TenantSettings`` field names match ``CoreConfig`` exactly, and a ``None`` override means
    "inherit the deployment default", so the overlay is a plain copy of the non-null values. Returns
    ``base`` unchanged when there is nothing to override (the common no-saved-settings case)."""
    update = overrides.model_dump(exclude_none=True)
    if not update:
        return base
    return base.model_copy(update=update)
