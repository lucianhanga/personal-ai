# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/) and the project follows
[Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

**Versioning policy (pre-1.0):** `MAJOR` stays `0` until the first stable release; `MINOR` bumps as
each milestone (M1, M2, …) lands; `PATCH` bumps for fixes/UX tweaks between milestones. The HTTP API
is versioned independently in the URL path (`/api/v1`) and surfaced as `info.version` in the
generated OpenAPI document.

## [Unreleased]

### Added
- **Speech-to-text (M9.2, #296/#298)**: **voice input**, on by default. A mic button in the
  composer records audio, transcribes it via an OpenAI-compatible `/v1/audio/transcriptions`
  endpoint, and drops the text into the composer to review before sending. The transcription
  endpoint and model are **per-tenant settings** (Settings → Voice) — point them at a **local
  whisper server** (whisper.cpp-server / faster-whisper-server / LocalAI; fully local, egress off
  on loopback) or OpenAI. New `Transcriber` port + `OpenAICompatTranscriber` adapter, built
  per-request from the tenant's effective config; `POST /api/v1/audio/transcribe`.
- **Vision (M9.1, #294)**: attach image(s) to a chat turn and a **vision-capable model sees them**.
  Image-attach button in the composer (with a hint when the selected model isn't a vision model),
  thumbnail previews, and the image(s) rendered in the user bubble. Images flow as data-URLs through
  the `ChatMessage` contract to both providers (Ollama `images` as raw base64; OpenAI `image_url`
  content parts). Per-turn (not persisted/indexed). First slice of **M9 Multimodal**.
- **Verification ladder (M8.2, #261)**: in the multi-agent graph, `accuracy_mode = "accurate"` adds
  an **LLM-judge verifier** after the critic that returns a schema-validated `Verdict`
  (pass/needs_revision/fail) and can route one more bounded researcher pass; `"standard"` skips it
  (fast). Security gates (the human approval gate) are never accuracy-gated. New reusable
  `generate_structured` core primitive (bounded, fail-closed, repair-retry via `RepairRequest`). The
  verifier step streams to the reasoning pane as a `verification` trace event.

## [0.7.0] — 2026-06-21

Milestone **M8.2** — multi-agent quality, per-tenant configuration, and a streamlined UI.

### Added
- **Agent mode selector** (`single` | `multi` | `custom`): `single` = the single-agent loop,
  `multi` = the planner → researcher → critic graph, `custom` = reserved. Per-tenant, persisted;
  supersedes the `agent_graph_enabled` flag (which still maps to `multi` for back-compat).
- **Per-tenant agent configuration**: edit each agent's system prompt and scope which tools/MCPs
  the researcher may use, from a new **Agents** settings panel.
- **Bounded reflection loop**: when the critic judges an answer materially inadequate (no real
  data, dead link, doesn't answer), the graph retries the researcher once with the critique as
  feedback before finalizing. Capped (1 retry) and only on a `REVISE` verdict.
- **Query understanding (contextualize)**: a follow-up is rewritten into a standalone request to
  anchor RAG + memory retrieval and tool queries; the original question still drives the answer.
  Skipped for first/standalone questions. The model is also told to reply in the user's language,
  and the **current date** is injected so agents don't dismiss recent dates as fabricated.
- **Per-tenant settings** (Postgres, RLS), in a new **Settings** view: model/agent/behavior
  preferences, the **document-indexing (embedding) engine**, **network egress** (enable + host
  allowlist), the API token, and the **turn timeout** (`agent_timeout_seconds`).
- **Network egress controls**: a Network settings panel (off by default, amber risk warning,
  confirm-on-enable) **and** one-click **allow-on-deny** — when a tool is blocked, the reasoning
  pane offers to allow that host from then on. Egress is now enforced **per tenant**.
- **Context composition view**: the side panel shows what was assembled into the prompt this turn
  (grounding, documents, memory, the interpreted request, …) with per-component token estimates and
  a hover overlay.
- **Schema-driven tool-argument auto-fix**: the gateway reads each tool's JSON Schema and repairs
  common model slips (rename a mislabeled argument, coerce a scalar to an array or a numeric string
  to a number, clamp a number to the min/max), re-validating so a wrong fix is never used; enum
  errors list the allowed values.

### Changed
- **UI redesign**: a **Chat | Settings** two-view split (settings moved out of the inline accordion
  into a dedicated view); a slimmer top bar with a single model selector that persists the choice;
  per-session toggles moved next to a **4-line composer** (Enter sends, Shift+Enter newline). The
  reasoning pane streams all agents with a faded per-agent color code (shared with the Agents
  config), a bigger font/window, and only the final agreed answer is shown as the reply.
- **Default embedding model** is now `qwen3-embedding:0.6b` (1024-dim, same schema as before).
- The backend now **loads `.env`** on startup, so documented `PERSONALAI_*` settings actually apply.

### Fixed
- The multi-agent **critic** now actually reviews (it was returning empty / dismissing real data);
  its review stays in the reasoning pane and never leaks into the answer.
- The agent no longer ends a turn on a `"let me…"` non-answer; tool-use narration is kept as
  reasoning, and the final answer streams again.
- Recognize all egress block message formats (including the built-in `http_fetch`).
- Diagnostics: surface the raw offending line on MCP stdio JSON-RPC parse errors.

## [0.6.0] — 2026-06-09

Milestones **M0–M6** complete.

### Added
- **M6 — single-agent loop**: the model autonomously calls tools through the gateway and **streams
  reasoning + answer** token-by-token (tool calls parsed from the provider stream, Ollama + OpenAI).
  Built-in `web_search` (DuckDuckGo); ordered per-message **Details** (reasoning + tool calls)
  persisted and shown collapsibly; in-progress markers; concurrent per-chat streaming; rename chats;
  per-chat **Activity** + **App logs**; context-usage meter; bounded `num_ctx`.
- **M5 — Tool/MCP gateway**: permissions, network egress allowlist, JSON-Schema I/O validation, risk
  approval, timeout, append-only audit; built-in calculator + http_fetch.
- **M4 — memory**: per-chat short-term summary + cross-chat long-term memory (view/edit/erase);
  incognito chats.
- **M3 — files + RAG**: ingestion → pgvector retrieval with citations.
- **M2 — provider portability**: remote OpenAI-compatible provider behind the same seam.
- **M1 — local chat**: streaming chat over local Ollama models.
- **M0 — skeleton**: hexagonal contracts/core, CI, structured outputs, security primitives,
  architecture research, roadmap, supply-chain/security/threat-model docs, repo scaffolding.
- **Versioning**: project semver (`VERSION` + this changelog) and a versioned HTTP API.

### Changed
- The HTTP API is now served under **`/api/v1`** (the `/health` and `/version` infrastructure
  endpoints stay unversioned); OpenAPI `info.version` reflects the project version.

[Unreleased]: https://github.com/lucianhanga/personal-ai/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/lucianhanga/personal-ai/releases/tag/v0.6.0
