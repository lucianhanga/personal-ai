# Local Chat (M1)

Run PersonalAI as a local, streaming chat app over your own Ollama models — fully offline.

## Prerequisites

- [Ollama](https://ollama.com) running locally (`ollama serve`) with at least one chat model
  pulled, e.g. `ollama pull qwen3.6:35b-a3b` (or a lighter `ollama pull qwen3:8b`).
- This repo set up: `make setup` (uv + pnpm).

## Run it

```bash
# terminal 1 — backend (loopback). Local mode is zero-login by default. Pick your default model.
PERSONALAI_DEFAULT_MODEL=qwen3.6:35b-a3b make run-backend

# terminal 2 — UI (Vite dev server)
pnpm --filter @personalai/ui dev
```

Open **http://localhost:5173**, pick a model, and chat. Replies stream in token by token. Everything
stays on loopback; network egress is off by default. In the default `app_mode=local` no login is
required; if you set `PERSONALAI_AUTH_TOKEN`, that bearer token then becomes **required** (enter it
in the UI). `app_mode=hosted` requires real login (see [backend API](../reference/backend-api.md)).

## Configuration (env)

| Variable | Default | Purpose |
|---|---|---|
| `PERSONALAI_AUTH_TOKEN` | (unset) | Optional bearer token. Local mode is zero-login when unset; if set, it becomes required. (Hosted mode uses cookie login instead — see backend API.) |
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
- **401 in the UI:** if you set `PERSONALAI_AUTH_TOKEN`, the API token field must match it (local
  mode needs no token unless you set one; hosted mode needs a login).

## Running local models on constrained RAM

On a machine with limited unified memory (e.g. a 48 GB Mac), getting a model to load is usually a
**memory-budget** problem, not a weights problem. The notes below come from real debugging sessions.

### How loading actually works

- Ollama **auto-loads any model that has been pulled** on the first request for it — you do not
  pre-load it. It only fails to load if the model **isn't pulled** (`ollama pull <model>`) or if
  **there isn't room** in RAM.
- The dominant memory cost at load time is often **not the weights** — it is the **KV cache**, which
  scales roughly as **`context_length × num_parallel`**. A large default context with parallelism
  can make even a mid-size model refuse to load while a much bigger model loads fine at a smaller
  context.
- Concrete example: Ollama's defaults of `OLLAMA_CONTEXT_LENGTH=262144` (256K) and
  `OLLAMA_NUM_PARALLEL=4` made a mid-size model unloadable. Setting `OLLAMA_CONTEXT_LENGTH=32768`
  and `OLLAMA_NUM_PARALLEL=1` fixed it — a 24 GB, 35B model then loaded in ~13 s.

### The macOS app overrides launchctl

The **Ollama macOS app stores the context length in its own settings DB** and injects it as an
environment variable, which **overrides anything you set with `launchctl setenv`**. To change it for
the app:

- Set it in the app's **Settings → Context length**, or edit the app's settings DB directly, then
- **Restart Ollama** so the new value is applied.

If you set `OLLAMA_CONTEXT_LENGTH` via `launchctl` and nothing changes, this is why — the app's own
setting is winning.

### Memory budget and co-residency

Everything resident must fit in RAM at once:

```
chat-model weights + chat-model KV cache + embedding model (RAG/memory) + your other apps  ≤  RAM
```

If it doesn't fit, Ollama **evicts** models to make room, and a chat model + the embedding model can
**ping-pong** (each request reloads the other), which feels like the app is hanging. Rule of thumb:
**pick a model and context size that fit alongside the embedding model** (`PERSONALAI_EMBED_MODEL`,
default `qwen3-embedding:0.6b`) **and** your other workloads — don't size the chat model to the full
machine.

### Troubleshooting: "model won't load" / appears to hang

Before assuming the weights are too big, check, in order:

1. `ollama ps` — is the model loaded, and is something else also resident (eviction/ping-pong)?
2. **Free RAM** — is there actually room for weights + KV + the embedding model?
3. `OLLAMA_CONTEXT_LENGTH` and `OLLAMA_NUM_PARALLEL` — a huge context or parallelism inflates the KV
   cache far beyond the weights. Lower both (e.g. `32768` and `1`).
4. Confirm the model is **pulled** (`ollama list`).

### Knobs

**PersonalAI** (sent to Ollama per request):

| Variable | Default | Purpose |
|---|---|---|
| `PERSONALAI_DEFAULT_MODEL` | `qwen3.6:35b-a3b` | Default chat model. |
| `PERSONALAI_OLLAMA_NUM_CTX` | `32768` | Context window sent as `num_ctx`; bounds the KV cache for the turn. |
| `PERSONALAI_OLLAMA_KEEP_ALIVE` | `30m` | How long Ollama keeps the model warm between turns (`-1` = never unload). |

**Ollama** (server-level, shrink the KV cache further):

```bash
OLLAMA_CONTEXT_LENGTH=32768   # default context; KV cache ≈ context_length × num_parallel
OLLAMA_NUM_PARALLEL=1         # one slot — biggest single KV-cache reduction
OLLAMA_FLASH_ATTENTION=1      # efficient attention
OLLAMA_KV_CACHE_TYPE=q8_0     # ~half the KV memory, negligible quality loss
OLLAMA_MAX_LOADED_MODELS=1    # don't hold multiple models in RAM
```

Note: on the macOS app, set `OLLAMA_CONTEXT_LENGTH` in the app's Settings (see above), not via
`launchctl`.
