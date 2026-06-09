# Local Chat (M1)

Run PersonalAI as a local, streaming chat app over your own Ollama models — fully offline.

## Prerequisites

- [Ollama](https://ollama.com) running locally (`ollama serve`) with at least one chat model
  pulled, e.g. `ollama pull qwen3.6:35b-a3b` (or a lighter `ollama pull qwen3:8b`).
- This repo set up: `make setup` (uv + pnpm).

## Run it

```bash
# terminal 1 — backend (loopback). Pick your default model.
PERSONALAI_AUTH_TOKEN=demo PERSONALAI_DEFAULT_MODEL=qwen3.6:35b-a3b make run-backend

# terminal 2 — UI (Vite dev server)
pnpm --filter @personalai/ui dev
```

Open **http://localhost:5173**, enter the API token (`demo`), pick a model, and chat. Replies
stream in token by token. Everything stays on loopback; network egress is off by default.

## Configuration (env)

| Variable | Default | Purpose |
|---|---|---|
| `PERSONALAI_AUTH_TOKEN` | (unset) | Bearer token required by `/api/v1/*`. Protected routes fail closed (503) if unset. |
| `PERSONALAI_DEFAULT_MODEL` | `qwen3.6:35b-a3b` | Default chat model. |
| `PERSONALAI_OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama server URL. |
| `PERSONALAI_BIND_HOST` / `PERSONALAI_BIND_PORT` | `127.0.0.1` / `8765` | Backend bind (loopback by default). |
| `PERSONALAI_ALLOWED_ORIGINS` | loopback + Vite ports | CORS allowlist for the browser UI. |

The UI reads `VITE_API_BASE` (default `http://127.0.0.1:8765`) and an optional `VITE_API_TOKEN`.

## Model notes (Apple Silicon, ~48 GB)

- **`qwen3.6:35b-a3b`** (MoE, ~3B active, 256K context, vision + tools) — capable default; first
  message loads ~23 GB, so give it a few seconds.
- **`qwen3:8b`** / **`gemma3:latest`** — faster for quick iteration.
- **Thinking models** (qwen3 family): the backend sends `think=false` by default so they answer
  cleanly. The `/api/v1/chat` body accepts `"think": true` to opt into the reasoning trace.

## How it works

```
Browser SPA (React)  --SSE-->  /api/v1/chat  -->  ModelProvider (ollama)  -->  Ollama REST API
        |                          |                    ^
   /api/v1/models  <-------------/             registered in the composition root (M0-4)
```

- The SPA streams Server-Sent Events from `POST /api/v1/chat`; `GET /api/v1/models` populates the
  model selector with detected capabilities. See [backend API](../reference/backend-api.md).
- The chat is **stateless** at M1 (the client sends the message history each turn); conversation
  persistence arrives in **M3**.
- The Ollama adapter is one implementation of the `ModelProvider` seam; a remote/OpenAI provider
  plugs into the same seam — see [Remote / frontier providers](./remote-providers.md) (M2).

## Verify against your real Ollama

```bash
PERSONALAI_OLLAMA_IT=1 uv run pytest providers/ollama/tests/test_integration.py -q
```
(Opt-in; skipped in CI. Override models with `PERSONALAI_IT_MODEL` / `PERSONALAI_IT_EMBED`.)

## Troubleshooting

- **"Backend not reachable" / CORS errors:** ensure the backend is running and the UI origin is in
  `PERSONALAI_ALLOWED_ORIGINS` (the loopback Vite ports are allowed by default).
- **Empty replies from a qwen3 model:** that's the thinking trace; the default `think=false` avoids
  it — make sure you're on the latest backend.
- **401 in the UI:** the API token field must match `PERSONALAI_AUTH_TOKEN`.

## Memory / context size (local models)

The KV cache grows with the context window, so on constrained unified memory (e.g. a 48 GB Mac) a
huge context can trigger swap. PersonalAI bounds it: **`PERSONALAI_OLLAMA_NUM_CTX`** (default
**32768**) is sent to Ollama as `num_ctx`. Lower it (e.g. `8192`) for less memory, raise it for
longer documents/agent runs. Shrink the KV cache further at the Ollama level:

```bash
OLLAMA_FLASH_ATTENTION=1      # efficient attention
OLLAMA_KV_CACHE_TYPE=q8_0     # ~half the KV memory, negligible quality loss
OLLAMA_MAX_LOADED_MODELS=1    # don't hold multiple models in RAM
```
