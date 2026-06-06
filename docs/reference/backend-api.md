# Backend API (loopback)

The PersonalAI backend is a FastAPI app that binds to **loopback by default** and is wired
through the composition root (M0-4). M0-5 ships the skeleton API; feature endpoints arrive in
later milestones.

## Running it

```bash
# protected routes need a token; health/version are public
PERSONALAI_AUTH_TOKEN=demo-token make run-backend
# or: PERSONALAI_AUTH_TOKEN=demo-token uv run python -m personalai_backend
```

Defaults: `http://127.0.0.1:8765`. Override with `PERSONALAI_BIND_HOST` / `PERSONALAI_BIND_PORT`.
OpenAPI docs are served at `/docs`.

## Endpoints

| Method | Path | Auth | Response | Notes |
|---|---|---|---|---|
| GET | `/health` | public | `{"status":"ok"}` | Liveness. |
| GET | `/version` | public | `{name, version}` | Service identity. |
| GET | `/api/status` | bearer token | `StructuredResult` | Example protected route returning a validated structured-output envelope. |
| POST | `/api/chat` | bearer token | `text/event-stream` (SSE) | Streaming chat over the active model provider (M1-3). |

```bash
curl http://127.0.0.1:8765/health
curl -H "Authorization: Bearer $PERSONALAI_AUTH_TOKEN" http://127.0.0.1:8765/api/status

# Streaming chat (SSE). Body is stateless: send the full message history.
curl -N -X POST http://127.0.0.1:8765/api/chat \
  -H "Authorization: Bearer $PERSONALAI_AUTH_TOKEN" -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"hello"}]}'
```

### `/api/chat`

- **Request:** `{ "messages": [{"role","content"}], "model"?: str, "think"?: bool }`. `model`
  defaults to `CoreConfig.default_model` (`qwen3.6:35b-a3b`); `think` defaults to `false` so
  reasoning ("thinking") models answer cleanly. Invalid bodies are rejected (422, fail-closed).
- **Response:** Server-Sent Events. Each `data:` frame is
  `{delta, thinking, done, finish_reason}`; on failure an `event: error` frame carries a
  `StructuredResult` error envelope. Conversation persistence arrives in M3.

## Security posture (M0-5)

- **Loopback by default** — LAN/remote is opt-in via `PERSONALAI_BIND_HOST` (see THREAT-MODEL).
- **Origin allowlist** — browser requests with an `Origin` not in `CoreConfig.allowed_origins`
  are rejected with `403`. Non-browser clients (curl, tests) send no `Origin` and are allowed.
- **Bearer-token auth** — protected routes require `Authorization: Bearer <token>`, compared in
  constant time. If no token is configured, protected routes are **fail-closed** (`503`), never open.
- **No egress** — the app makes no outbound calls; `egress_enabled` defaults to `false`.
- **Structured outputs** — responses use the schema models (ADR-0003); `/api/status` returns a
  validated `StructuredResult`.

Configuration is `CoreConfig` (see [Dependency injection & registries](./dependency-injection.md));
proper secrets handling is M0-10.
