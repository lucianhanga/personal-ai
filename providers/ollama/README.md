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

## Ollama notes

Validated against Ollama 0.30.x. Cloud models (entries with `remote_host`, e.g. `*:cloud`) are
reported as `local=False`; calling them logs a warning (Ollama proxies them off-machine). Opt-in
remote/cloud generation is handled by the separate `openai_compat` provider.

Tool calling (a `tools` request field plus `tool_calls` parsing) and vision (`images` on
`ChatMessage`) are both supported — for vision use `qwen3-vl` (`llama3.2-vision`/`mllama` is
unsupported on 0.30).

**Optional, not yet wired:** `embed(dimensions=)` (Matryoshka); the `insert` (FIM) capability.
