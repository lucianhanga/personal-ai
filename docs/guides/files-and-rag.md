# Files + RAG: chat with your documents (M3)

PersonalAI can ingest your files and use them to ground answers, with citations and persistent
conversation history. This is **local-first**: parsing, embeddings, and storage all run on your
machine.

## 1. Prerequisites

- **PostgreSQL + pgvector** via Docker:
  ```bash
  make db        # starts pgvector/pgvector:pg17 (stop with: make db-down)
  ```
- **Ollama** running with an embedding model:
  ```bash
  ollama pull qwen3-embedding:0.6b   # 1024-dim; matches the vectors schema
  ```
- Backend + UI:
  ```bash
  set -a; source .env; set +a            # optional (e.g. remote provider)
  PERSONALAI_AUTH_TOKEN=demo make run-backend
  pnpm --filter @personalai/ui dev       # http://localhost:5173  (token: demo)
  ```

If the database is unreachable the app still runs for plain chat; file/RAG/history features return
`503` and the UI hides the documents/conversations panels.

## 2. Ingest a file

**UI:** the **Documents** panel → pick a `.txt`, `.md`, `.pdf`, or `.docx`. It is parsed, chunked,
embedded, and stored; it appears in the list with a chunk count, and **Use my documents** turns on.
A **scanned / image-only PDF** (no text layer) is **OCR'd on-device** so it indexes like any other
document. To keep whole **folders** continuously indexed (instead of one-off uploads), and to browse
the **knowledge graph** of entities across your corpus, see
[Documents & folders](./documents-and-folders.md).

**API:**
```bash
curl -X POST http://127.0.0.1:8765/api/v1/files \
  -H "Authorization: Bearer demo" -F "file=@notes.pdf"
curl -H "Authorization: Bearer demo" http://127.0.0.1:8765/api/v1/files          # list
curl -X DELETE -H "Authorization: Bearer demo" http://127.0.0.1:8765/api/v1/files/<id>
```

## 3. Ask with RAG

With **Use my documents** on (or `"use_rag": true` via the API), the retrieval query is embedded, the
top-k chunks are retrieved from pgvector, and they are passed to the model as **reference context**
with `[n]` citations. The UI shows a **Sources** line under the answer.

For a **follow-up** message, retrieval is anchored on the **contextualized standalone query** (the
last message rewritten into a self-contained request using recent history) rather than the raw
elliptical message, so *"and the second one?"* still retrieves the right chunks. The original
question still drives the answer; first/standalone questions skip the rewrite. See
[the agent guide](./agent.md#query-contextualization-follow-ups).

```bash
curl -N -X POST http://127.0.0.1:8765/api/v1/chat \
  -H "Authorization: Bearer demo" -H "Content-Type: application/json" \
  -d '{"model":"qwen3:8b","use_rag":true,
       "messages":[{"role":"user","content":"What does my document say about X?"}]}'
```

### How it works

```
file -> parse (txt/md/pdf/docx) -> chunk (overlapping) -> embed (qwen3-embedding:0.6b)
     -> pgvector (cosine/HNSW)            query -> embed -> top-k -> inject as context -> answer + citations
```

### Security

Retrieved text is treated as **untrusted data, not instructions** (a system message says so) — a
basic guardrail against prompt injection from document contents. Files are parsed for **text only**
(no active content is executed). Embeddings are local by default (`embed_provider=ollama`).

## 4. Conversation history

Send a message and a conversation is created automatically (titled from your first message). The
**conversations** panel lists past chats; click one to reload its messages, or **+ New chat** to
start fresh. History is stored in Postgres (`conversations` + `messages`); deleting a conversation
removes its messages. Conversation content is stored verbatim (it's your data); secret redaction
applies to logs/audit, not to your messages.

API: `POST/GET/GET{id}/PATCH{id}/DELETE{id} /api/v1/conversations` (PATCH renames); pass
`"conversation_id"` to `/api/v1/chat` to persist a turn.

## 5. Configuration

| Env var | Default | Purpose |
|---|---|---|
| `PERSONALAI_DATABASE_URL` | `postgresql://personalai@127.0.0.1:5432/personalai` | Postgres DSN |
| `PERSONALAI_EMBED_PROVIDER` | `ollama` | provider used for embeddings |
| `PERSONALAI_EMBED_MODEL` | `qwen3-embedding:0.6b` | embedding model (must be 1024-dim) |
| `PERSONALAI_MAX_UPLOAD_BYTES` | `10000000` | max upload size |

The embedding (document-indexing) **engine and model**, and the max upload size, are also saved
**per-tenant** in **Settings → Documents** (`embed_provider` / `embed_model` / `max_upload_bytes` in
`TenantSettings`); an unset value inherits the deployment default above. The model must still produce
1024-dim vectors to match the schema.

## 6. Troubleshooting

- **Documents panel missing / 503:** the database isn't reachable — run `make db`.
- **Upload fails with a dimension error:** the embedding model must produce 1024-dim vectors
  (e.g. `qwen3-embedding:0.6b`). Changing models requires a new migration.
- **Unsupported file type:** only txt/md/pdf/docx are supported in v1 (richer parsing — Tika/Docling
  — can be added behind the `ModalityHandler` seam later).

## 7. Full integration test (opt-in)

A real end-to-end pipeline test (Postgres + Ollama embeddings) runs only when asked:
```bash
PERSONALAI_RAG_IT=1 uv run pytest apps/backend/tests/test_rag_integration.py -q
```
(Skipped in CI, which exercises the same paths with a Postgres service + fake embeddings.)
