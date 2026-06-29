# Backend API (loopback)

The PersonalAI backend is a FastAPI app that binds to **loopback by default** and is wired
through the composition root. Application endpoints are **versioned under `/api/v1`**; `/health`
and `/version` are unversioned infrastructure endpoints. The OpenAPI document's `info.version`
tracks the project version (see [`VERSION`](../../VERSION) / [`CHANGELOG.md`](../../CHANGELOG.md);
currently `0.9.0`).

## Running it

```bash
# local mode (default): zero-login — no token needed; everything runs as tenant #1
make run-backend
# or set a bearer token to require it (still single-user); or PERSONALAI_APP_MODE=hosted for real login
```

Defaults: `http://127.0.0.1:8765`. Override with `PERSONALAI_BIND_HOST` / `PERSONALAI_BIND_PORT`.
OpenAPI docs are served at `/docs`.

## Authentication (ADR-0010)

Auth is resolved per request into a fail-closed `SecurityContext{subject_id, tenant_id}` by the
`require_context` dependency, precedence: **cookie session → bearer token (`PERSONALAI_AUTH_TOKEN`,
a degenerate credential) → local dev-login → 401 (hosted)**.
- **`app_mode=local` (default):** zero-login — a dev `SecurityContext` (tenant #1) is auto-applied,
  so the bearer/cookie are optional. If `PERSONALAI_AUTH_TOKEN` is set, it becomes required.
- **`app_mode=hosted`:** real login via `/api/v1/auth/*` (argon2id passwords → opaque server-side
  session in a `__Host-` cookie) + double-submit **CSRF** on unsafe requests; no dev-login.

Auth endpoints: `POST /api/v1/auth/signup|login|logout`, `GET /api/v1/auth/session/me`. Every other
`/api/v1/*` route requires a resolved context; `/health` and `/version` stay unversioned + public.

## Endpoints

All application routes live under `/api/v1` and require an authenticated `SecurityContext` (see
Authentication above). `/health` and `/version` stay unversioned and public.

### Infrastructure (unversioned, public)

| Method | Path | Response | Notes |
|---|---|---|---|
| GET | `/health` | `{"status":"ok"}` | Liveness. |
| GET | `/version` | `{name, version}` | Service identity (`version` = project version). |

### Status & discovery

| Method | Path | Response | Notes |
|---|---|---|---|
| GET | `/api/v1/status` | `StructuredResult` | Runtime config snapshot (provider, vector repo, bind host, egress flag). |
| GET | `/api/v1/providers` | `StructuredResult` | Registered providers + the default. |
| GET | `/api/v1/models` | `StructuredResult` | A provider's models + capabilities; `?provider=` to choose. |

### Chat

| Method | Path | Response | Notes |
|---|---|---|---|
| POST | `/api/v1/chat` | `text/event-stream` (SSE) | Streaming chat. See the request/SSE detail below. |
| POST | `/api/v1/chat/{run_id}/resume` | `text/event-stream` (SSE) | Resume a run suspended at a durable gate (answer-approval or egress-approval). Body `{decision, conversation_id?, provider?}` where `decision` ∈ `approve`/`reject` (answer gate) or `egress_allow_once`/`egress_allow_always`/`egress_deny` (egress gate). The backend dispatches on the gate's `reason` read from the checkpoint, not the body. Tenant-scoped (foreign `run_id` → 404) and subject-scoped (a different subject in the same tenant → 403). |

### Files & RAG

| Method | Path | Response | Notes |
|---|---|---|---|
| POST | `/api/v1/files` | `StructuredResult` | Upload a file (txt/md/pdf/docx) → parse/chunk/embed/store. Scanned PDFs are OCR'd on-device; global documents also get named-entity extraction. |
| GET | `/api/v1/files` | `StructuredResult` | List ingested documents (each carries an `entity_count`). |
| DELETE | `/api/v1/files/{document_id}` | `StructuredResult` | Delete a document, its vectors, and its entity mentions. |
| POST | `/api/v1/files/extract` | `StructuredResult` | Extract text from an uploaded doc (no storage) for the per-question attachment flow. Data includes `ocr` (bool) + `pages` when a scanned PDF was OCR'd. |
| POST | `/api/v1/conversations/{id}/documents` | `StructuredResult` | Tier-2 ingest-at-attach: index a large attachment into the conversation's RAG scope (idempotent by content hash). |

### Folder sources (Documents v2)

Continuously-synced local folders → the global RAG corpus. All require_context; background sync is local-provider-only / fail-closed.

| Method | Path | Response | Notes |
|---|---|---|---|
| POST | `/api/v1/folders` | `StructuredResult` | Register a folder. Body `{path, label?, recursive?, include_globs?, exclude_globs?, max_file_mb?}`; validates the absolute path (errors `E_FOLDER_NOT_FOUND`/`E_FOLDER_NOT_A_DIR`/`E_FOLDER_EXISTS`) and kicks the initial sync. |
| GET | `/api/v1/folders` | `StructuredResult` | List folder sources + per-source status counts. |
| GET | `/api/v1/folders/{id}` | `StructuredResult` | Source + paginated per-file status (`?status=&after=&limit=`). |
| DELETE | `/api/v1/folders/{id}` | `StructuredResult` | Remove a source and purge its indexed chunks + entities (reports `purged_documents`). |
| POST | `/api/v1/folders/{id}/resync` | `StructuredResult` | Force a full reconciliation (`E_FOLDER_PAUSED` if paused). |
| POST | `/api/v1/folders/{id}/pause` · `/resume` | `StructuredResult` | Stop / start watching + syncing. |
| GET | `/api/v1/folders/{id}/events` | `text/event-stream` (SSE) | Live progress: `progress` frames (`{id,status,counts}`) until idle, then a terminal `done`. |

### Entities (knowledge graph)

| Method | Path | Response | Notes |
|---|---|---|---|
| GET | `/api/v1/entities` | `StructuredResult` | List entities (`?type=&q=&limit=`); `q` is a fuzzy name search. |
| GET | `/api/v1/entities/stats` | `StructuredResult` | Corpus-wide entity stats (exact total + per-type breakdown) for the Knowledge corpus view. |
| GET | `/api/v1/entities/{id}` | `StructuredResult` | An entity + its source `documents` + graph `edges` (`{relation, dst_entity_id}`). |
| GET | `/api/v1/entities/{id}/neighborhood` | `StructuredResult` | The entity's co-occurrence/edge neighborhood for the graph view. |
| POST | `/api/v1/entities/reconcile` | `StructuredResult` | Run conservative post-NER entity resolution (merge near-duplicate names). |
| GET | `/api/v1/documents/{document_id}/entities` | `StructuredResult` | Entities extracted from one document. |
| GET | `/api/v1/documents/{document_id}/chunks` | `StructuredResult` | The document's stored chunks (the Knowledge chunk inspector). |

### Conversations

| Method | Path | Response | Notes |
|---|---|---|---|
| POST | `/api/v1/conversations` | `StructuredResult` | Create a conversation (`{title?, incognito?}`). |
| GET | `/api/v1/conversations` | `StructuredResult` | List conversations (most-recent first). |
| GET | `/api/v1/conversations/{id}` | `StructuredResult` | Get a conversation + its messages (each message carries `meta`). |
| PATCH | `/api/v1/conversations/{id}` | `StructuredResult` | Rename a conversation (`{title}`). |
| DELETE | `/api/v1/conversations/{id}` | `StructuredResult` | Delete a conversation (cascades messages). |

### Memory

| Method | Path | Response | Notes |
|---|---|---|---|
| GET | `/api/v1/memory` | `StructuredResult` | List long-term memories. |
| PATCH | `/api/v1/memory/{id}` | `StructuredResult` | Edit a memory's text (`{text}`). |
| DELETE | `/api/v1/memory/{id}` | `StructuredResult` | Delete a memory. |
| DELETE | `/api/v1/memory` | `StructuredResult` | Forget everything. |

### Tools & logs

| Method | Path | Response | Notes |
|---|---|---|---|
| GET | `/api/v1/tools` | `StructuredResult` | List tool manifests (name, version, risk, permissions, JSON-Schema I/O). |
| POST | `/api/v1/tools/invoke` | `StructuredResult` | Invoke a tool through the gateway (grants + risk approval enforced). |
| GET | `/api/v1/tools/log` | `StructuredResult` | The gateway tool-audit entries; `?conversation_id=` filters per chat (**Activity**). |
| GET | `/api/v1/logs` | `StructuredResult` | Recent application logs; `?conversation_id=` filters per chat (**App logs**). |

```bash
curl http://127.0.0.1:8765/health
curl -H "Authorization: Bearer $PERSONALAI_AUTH_TOKEN" http://127.0.0.1:8765/api/v1/status

# Streaming chat (SSE). Body is stateless unless you pass a conversation_id.
curl -N -X POST http://127.0.0.1:8765/api/v1/chat \
  -H "Authorization: Bearer $PERSONALAI_AUTH_TOKEN" -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"hello"}]}'
```

### `/api/v1/chat`

- **Request:** `{ "messages": [{"role","content"}], "model"?, "provider"?, "think"?: false,
  "use_rag"?: false, "rag_top_k"?: 4, "conversation_id"?, "use_memory"?: false,
  "use_tools"?: false, "approve_tools"?: false }`.
  - `model` defaults to `CoreConfig.default_model` (`qwen3.6:35b-a3b`); `provider` overrides the
    default provider for this call.
  - `think` defaults to `false` so reasoning ("thinking") models answer cleanly.
  - `use_rag` grounds the answer in ingested documents and emits a `citations` SSE frame.
  - `conversation_id` persists the turn (user + assistant messages) and enables short-term memory
    folding for that chat.
  - `use_memory` injects relevant long-term memories (skipped for incognito conversations).
  - `use_tools` runs the **single-agent loop** (the model calls tools through the gateway);
    `approve_tools` approves HIGH/CRITICAL-risk tools for that turn.
  - Invalid bodies are rejected (422, fail-closed).
- **Response:** Server-Sent Events. Frame types:
  - `data: {delta, thinking?, done, finish_reason}` — answer (and, in plain chat, reasoning) tokens.
  - `event: citations` — RAG sources (when `use_rag` is on).
  - `event: tool` — `{phase: "call"|"result", tool, args, ok, output, error}` (when `use_tools`).
    In the agent loop, reasoning streams as `data: {thinking}` frames.
  - `event: plan` / `event: critique` / `event: verification` — `{kind, text}` planner / critic /
    verifier steps, emitted on the multi-agent path (`agent_mode="multi"`, or the legacy
    `PERSONALAI_AGENT_GRAPH_ENABLED`). The `citations` frame on this path carries multi-source
    provenance (`source_kind` / `merged_from`).
  - `event: approval_request` — a durable gate suspended the turn; the stream ends without `done`.
    Two shapes by `reason` (continue with `POST /api/v1/chat/{run_id}/resume`):
    - **answer gate** (`PERSONALAI_AGENT_HUMAN_GATE`) — `{run_id, reason:"approve_answer", answer,
      critique}`.
    - **egress gate** (always armed when the graph runs with a checkpointer) —
      `{run_id, reason:"egress_approval", blocked_host, tool, args}` (the payload is whitelisted to
      these client-facing keys; the blocked host lives in the checkpoint, not the body). See
      [the agent guide](../guides/agent.md#durable-gates-answer-approval--egress-approval) and
      [ADR-0013](../architecture/adr/0013-egress-approval-gate.md).
  - `event: usage` — `{prompt_tokens, completion_tokens, total_tokens, context_limit}` for the
    UI context-usage meter (`context_limit` is set only for the local Ollama provider). The same
    counts (plus `elapsed_ms`) are persisted per assistant message under `meta.usage` and shown as a
    per-message footer + side-panel chat totals.
  - `event: error` — a `StructuredResult` error envelope on failure.
- **Persisted detail (`meta`):** when a turn is persisted to a conversation, the assistant message
  carries a `meta` object returned by `GET /api/v1/conversations/{id}`:
  - `meta.trace` — an ordered timeline (reasoning + tool calls/results), surfaced per message as
    **Details** (when the turn used tools/reasoning).
  - `meta.usage` — `{prompt_tokens, completion_tokens, total_tokens, elapsed_ms}` for the
    per-message token/time footer and per-chat totals.
  - `meta.context` — the prompt-assembly snapshot `{items: [{label, count, chars}], total_chars}`
    that drives the per-message **Context (~N tokens)** disclosure and the info-panel timeline.
  - Each message in the response also carries `created_at` (ISO 8601), used by the info-panel
    **Activity timeline** to order turns.

### Providers (local + remote)

The active provider is `PERSONALAI_MODEL_PROVIDER` (default `ollama`); requests may override it
per call (`?provider=` / `"provider"`). A **remote OpenAI-compatible** provider (`openai`) is
registered when `PERSONALAI_OPENAI_API_KEY` is set. Remote calls go through the egress allowlist,
so they require `PERSONALAI_EGRESS_ENABLED=true` and the host in `PERSONALAI_ALLOWED_EGRESS_HOSTS`
(e.g. `api.openai.com`); otherwise they fail closed. See
[Remote / frontier providers](../guides/remote-providers.md).

## Security posture

- **API versioning** — application endpoints are served under `/api/v1`; `/health` and `/version`
  stay unversioned; OpenAPI `info.version` reflects the project version.
- **Loopback by default** — LAN/remote is opt-in via `PERSONALAI_BIND_HOST` (see THREAT-MODEL). A
  non-loopback bind without an auth token is **refused at startup**.
- **Origin allowlist** — browser requests with an `Origin` not in `CoreConfig.allowed_origins`
  are rejected. Non-browser clients (curl, tests) send no `Origin` and are allowed.
- **Bearer-token auth** — protected routes require `Authorization: Bearer <token>`, compared in
  constant time. If no token is configured, protected routes are **fail-closed** (`503`), never open.
- **Egress fail-closed** — outbound calls are disabled by default. Enabling egress with an **empty
  allowlist denies all hosts**; set `PERSONALAI_ALLOWED_EGRESS_HOSTS`, or opt into open egress with
  `PERSONALAI_EGRESS_ALLOW_ANY=true`.
- **Structured outputs** — responses use the schema models (ADR-0003); `/api/v1/status` returns a
  validated `StructuredResult`.

Configuration is `CoreConfig` (see [Dependency injection & registries](./dependency-injection.md)).
</content>
</invoke>
