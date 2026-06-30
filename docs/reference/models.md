# Model suite (the layered model stack)

## Purpose

PersonalAI does not use one model for everything. It runs a small set of models, each
sized to its job: small, fast models for narrow, high-volume tasks (embeddings, entity
extraction, transcription) and one strong chat model for reasoning, generation, and
validation. This document lists every model role, its actual default, the config field
that controls it, whether the user can change it, and the capability schema the router
uses to decide what a model is allowed to do.

The layered idea matters for memory and latency: the NER model and the embedding model
are deliberately *not* the heavy chat model, so they stay cheap and fit in memory
alongside it.

## Source of Truth

- Per-role defaults: `core/src/personalai_core/config.py` (`CoreConfig`).
- User-overridable preferences: `contracts/src/personalai_contracts/schemas/settings.py`
  (`TenantSettings`); the overlay is `effective_config()` in `config.py`.
- Capability schema: `contracts/src/personalai_contracts/ports/model_provider.py`.
- Model-selector data: `GET /api/v1/models` in
  `apps/backend/src/personalai_backend/app.py` (`api_models`).
- Capability detection: Ollama in
  `providers/ollama/src/personalai_provider_ollama/provider.py`
  (`_capabilities_from`); OpenAI-compatible in
  `providers/openai_compat/src/personalai_provider_openai/provider.py`
  (`_remote_capabilities`).

When this document and the code disagree, the code wins.

## Current Behavior

### Per-role model table

| Role | Default | Provider | Config field | User-selectable? | Purpose |
| --- | --- | --- | --- | --- | --- |
| Chat / generation | `qwen3.6:35b-a3b` | `ollama` | `default_model` | Yes (`default_model`) | The strong model. Drives the single-agent loop and the multi-agent researcher, the standalone-query rewrite, vision captioning, the NER prompts (model id aside), STM summarization, and the memory/judge verdicts. |
| Reasoning amount | `low` | n/a | `default_reasoning` | Yes (`default_reasoning`) | How hard the chat model thinks when a turn does not specify: `off` / `low` / `medium` / `high`. `low` keeps thinking on but bounded so large models do not over-deliberate. |
| Embeddings | `qwen3-embedding:0.6b` | `ollama` | `embed_model` / `embed_provider` | Yes (`embed_model`, `embed_provider`) | Embeds chunks at RAG ingest and embeds the query at retrieval and long-term-memory recall. |
| Reranker (optional) | `Qwen/Qwen3-Reranker-0.6B` | `hf_reranker` (cross-encoder) | `rerank_enabled` (default `False`), `rerank_model` | No (env-only: `RERANK_ENABLED` / `RERANK_MODEL`) | Optional cross-encoder that re-scores the hybrid retrieval hits after retrieval, on both the single-agent and multi-source paths. **Off by default** — when disabled (the default), ranking is RRF only and the heavy ML stack (transformers/torch) is not installed. |
| NER / entity extraction | `qwen3:14b` | `ollama` (dedicated loopback runner) | `ner_model`, `ner_num_ctx` (8192), `ner_memory_fraction` (0.75) | No (env-only) | Extracts named entities and relations for the knowledge graph (KAG). Runs on its OWN small model on a dedicated loopback Ollama runner, NOT the chat model. |
| Vision | the active chat model **if** `caps.vision` | `ollama` | `default_model` (runtime capability check) | Indirectly (pick a vision-capable chat model) | Captions attached images. Gated by a runtime capability check; a non-vision chat model returns `E_NO_VISION_MODEL`. |
| Judge / validation | the turn's chat model (no dedicated default) | follows chat | `default_model` | Follows chat model | Critic/verifier verdicts and the post-turn memory-consolidation verdict. |
| Speech-to-text (STT) | `large-v3-turbo` | `local` (faster-whisper) | `transcribe_*` | Yes (`transcribe_*`) | In-process Whisper by default; `openai_compat` calls a remote/local Whisper server. |
| Text-to-speech (TTS) | browser speech synthesis | client-side (no server model) | `tts_enabled` | Toggle only | Reads answers aloud in the browser; there is no server-side TTS model. |

Notes:

- The chat model id `qwen3.6:35b-a3b` is a Qwen3 mixture-of-experts (MoE, `...a3b`)
  model. The NER pipeline adapts its window size and prompt for MoE vs dense models
  (see [extraction pipeline](../architecture/extraction-pipeline.md)).
- The NER model is loaded through a *separate* loopback `OllamaProvider` built at
  `ner_num_ctx`, with a fail-closed local-only guard (it must not egress) and a
  memory-aware admission gate. It is `PERSONALAI_NER_MODEL` / env-only and is **not**
  exposed in `TenantSettings`.
- `default_reasoning` is the tenant default behind per-agent reasoning overrides; a
  per-request `reasoning` value (off/low/medium/high) still wins for that turn.

### Provider context window

For the Ollama provider, the KV-cache context window is bounded by `ollama_num_ctx`
(default `32768`). The `usage` SSE event reports `context_limit = ollama_num_ctx` for
Ollama and `null` for the OpenAI-compatible provider.

## What the user can choose

The model selector (in **Settings -> Agents -> Defaults**) is seeded from `GET /api/v1/models`,
which returns:

```json
{ "default_model": "<tenant default>", "models": [ { "name": "...", "local": true, "capabilities": { ... } } ] }
```

The selector is the single source of truth for the active chat model and writes the
chosen value back through `PUT /settings` (persisted as the tenant's `default_model`). A
sibling endpoint returns `{ "default": "<provider>", "providers": [...] }` for the active
provider, which also round-trips through `/settings`.

User-overridable fields live in `TenantSettings` (every field optional; a blank/`None`
value means "inherit the deployment default"):

- Models: `model_provider` (`ollama` | `openai_compat`), `default_model`, `ollama_host`,
  `ollama_num_ctx`, `ollama_keep_alive`, `embed_provider`, `embed_model`,
  `openai_base_url`.
- Reasoning: `default_reasoning` (`off` | `low` | `medium` | `high`).
- Voice: `transcribe_enabled`, `transcribe_provider`, `transcribe_base_url`,
  `transcribe_model`, `transcribe_language`, `tts_enabled`.

Server/boot/secret settings (auth token, database URL, API keys, bind host/port, CORS
origins, sessions, audit sink) are environment-only and never serialized through the
settings API. The NER model is also env-only.

## Capability schema

`model_provider.py` defines the capability contract the router uses:

```python
@dataclass(frozen=True)
class ModelCapabilities:
    text: bool = True
    vision: bool = False
    embeddings: bool = False
    tool_calling: bool = False
    structured_output: bool = False
    thinking: bool = False
    max_context_tokens: int | None = None

@dataclass(frozen=True)
class ModelDescriptor:
    name: str
    capabilities: ModelCapabilities
    local: bool = True
```

The `ModelProvider` protocol exposes `capabilities(model)`, `generate(request)`,
`stream(request)`, `list_models()`, and `embed(texts, model)`.

How capabilities are detected:

- Ollama (`_capabilities_from`): maps the runtime's capability strings to fields ---
  `text = "completion"`, `vision = "vision"`, `embeddings = "embedding"`,
  `tool_calling = "tools"`, `thinking = "thinking"`, and `structured_output = "completion"`
  (Ollama can constrain any completion model's output to a JSON schema). `max_context_tokens`
  comes from the model's reported context length.
- OpenAI-compatible (`_remote_capabilities`): static --- `text`, `tool_calling`, and
  `structured_output` are `True`; `vision` and `embeddings` are `False`;
  `max_context_tokens` is `None`.

## What we deliberately do NOT use

The docs describe the system as built, not as once proposed:

- **No GLiNER (or any dedicated NER model architecture).** Entity extraction is plain
  LLM structured output over the document text using the NER model. See the
  [extraction pipeline](../architecture/extraction-pipeline.md).
- **No reranker in the default path.** Ranking is Reciprocal Rank Fusion (RRF, `k = 60`)
  --- inside the hybrid vector source (dense + lexical) and, on the multi-source path,
  across sources. An optional cross-encoder reranker (see the model table above) can be
  enabled with `RERANK_ENABLED`, but it is off by default. See
  [how context is built](../architecture/context-assembly.md).

## Relevant Files

- `core/src/personalai_core/config.py`
- `contracts/src/personalai_contracts/schemas/settings.py`
- `contracts/src/personalai_contracts/ports/model_provider.py`
- `apps/backend/src/personalai_backend/app.py` (`api_models`, `describe_image`)
- `providers/ollama/src/personalai_provider_ollama/provider.py`
- `providers/openai_compat/src/personalai_provider_openai/provider.py`

## Related Decisions

- ADR-0001 (config-driven adapter selection; adapters never import each other).
- ADR-0002 (local-first, Ollama as the default provider).
- ADR-0012 (LangGraph multi-agent orchestration).

## Last Updated Notes

Verified against the code on 2026-06-30. Key facts confirmed in source: chat default
`qwen3.6:35b-a3b` with `default_reasoning="low"`; embeddings `qwen3-embedding:0.6b`; NER
`qwen3:14b` at `ner_num_ctx=8192`, `ner_memory_fraction=0.75` (env-only, dedicated
loopback runner); STT `large-v3-turbo` (`local`); TTS browser-side. No GLiNER; ranking is
RRF by default, with an optional flag-gated cross-encoder reranker (`RERANK_ENABLED`, off
by default, `Qwen/Qwen3-Reranker-0.6B`).
