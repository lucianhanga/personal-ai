# providers/ollama (`personalai_provider_ollama`)

A `ModelProvider` adapter (ADR-0002) for a local **Ollama** server. Talks to Ollama's REST API
(`http://127.0.0.1:11434` by default) via httpx; depends inward on `personalai_contracts` only and
never imports the core or other adapters (ADR-0001).

- `capabilities(model)` — detects text/vision/embeddings/tools/thinking + context length.
- `generate(request)` — non-streaming chat via `/api/chat` (supports JSON-schema structured output).
- `stream(request)` — streaming chat (SSE-friendly chunks, including `thinking`).
- `list_models()` — from `/api/tags` (capabilities + context length + `remote_host`), falling back
  to `/api/show` only when context length is missing.
- `embed(texts, model, truncate=True)` — embeddings via `/api/embed`.

Registered in the backend composition root under the name `ollama`. The default chat model and
host are set in `CoreConfig` (`PERSONALAI_DEFAULT_MODEL`, `PERSONALAI_OLLAMA_HOST`).

## Ollama 0.30 notes

Validated against Ollama 0.30.x. Cloud models (entries with `remote_host`, e.g. `*:cloud`) are
reported as `local=False`; calling them logs a warning (Ollama proxies them off-machine) until
explicit remote-provider routing lands in M2.

**Planned (need contract changes, deferred):**
- **M2:** explicit remote/cloud routing; `think` string levels (`low`/`medium`/`high`) — `bool` works today.
- **M4 (tools):** `tool_calls` / `tool_call_id` on `ChatMessage`; handle streaming tool-call chunks; wire a `tools` request field.
- **M5 (vision):** `images` on `ChatMessage`. Note: `llama3.2-vision` is unsupported on 0.30 (`mllama`); use `qwen3-vl`.
- **Optional:** `embed(dimensions=)` (Matryoshka); the `insert` (FIM) capability.
