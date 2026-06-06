# providers/ollama (`personalai_provider_ollama`)

A `ModelProvider` adapter (ADR-0002) for a local **Ollama** server. Talks to Ollama's REST API
(`http://127.0.0.1:11434` by default) via httpx; depends inward on `personalai_contracts` only and
never imports the core or other adapters (ADR-0001).

- `capabilities(model)` — detects text/vision/embeddings/tools + context length from `/api/show`.
- `generate(request)` — non-streaming chat via `/api/chat` (supports JSON-schema structured output).
- `embed(texts, model)` — embeddings via `/api/embed`.
- Streaming (`stream()`) is added in M1-2; model listing in M1-4.

Registered in the backend composition root under the name `ollama`. The default chat model and
host are set in `CoreConfig` (`PERSONALAI_DEFAULT_MODEL`, `PERSONALAI_OLLAMA_HOST`).
