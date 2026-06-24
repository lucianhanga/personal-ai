# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/) and the project follows
[Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

**Versioning policy (pre-1.0):** `MAJOR` stays `0` until the first stable release; `MINOR` bumps as
each milestone (M1, M2, …) lands; `PATCH` bumps for fixes/UX tweaks between milestones. The HTTP API
is versioned independently in the URL path (`/api/v1`) and surfaced as `info.version` in the
generated OpenAPI document.

## [Unreleased]

## [0.8.3] — 2026-06-24

Milestones **M8.1 → M8.3** (multi-agent quality, per-tenant configuration, the durable
human-in-the-loop gates, and the transparency panel) plus the M-Bench benchmark harness and the
M9 Multimodal trio (vision · STT · TTS).

### Fixed
- **Attached images now survive a reload (#384)**: a user message's attached images were sent to the
  model but never persisted, so they vanished when the conversation was reopened. The user turn now
  stores its images and `GET /conversations/{id}` returns them.

### Added
- **Per-step timestamps in the Activity timeline (#384)**: each trace item (reasoning, tool call,
  planner/critic/verify) is stamped with its own UTC time the moment it happens (in the turn→SSE
  mapper), and the same `ts` rides both the live SSE stream and the persisted `meta.trace` — so the
  timeline shows real `HH:MM:SSZ` per step live *and* on reload, falling back to the turn time for
  turns recorded before this change.
- **Blocking egress-approval gate (#380 backend, #381 UI)**: a **second** durable LangGraph
  human-in-the-loop gate (alongside the M8.1 answer-approval gate). When a multi-agent researcher
  tool's outbound call targets a host that is **not** on the tenant's allowlist, the run **pauses
  durably** (LangGraph `interrupt()` + the tenant-scoped `TenantCheckpointSaver`) and emits an
  `approval_request` SSE with `reason:"egress_approval"`, `blocked_host`, `tool`, `args` — instead of
  silently failing the call and continuing. The user chooses **Allow once** (this run only, not
  persisted), **Allow always** (persist the host to the tenant allowlist, audited), **Don't allow**
  (resume with the egress error), or **More info** (the redacted outbound args). On an allow, **only
  the blocked tool is retried** (prior succeeded tools never re-fire) via a checkpointed resume
  frame; the agent loop stays engine-agnostic (it emits an `egress_blocked` event; the graph's
  `egress_gate` node fires the interrupt). Security: the blocked host is read from the **checkpoint,
  never the request body**; resume is **subject-scoped** (a different subject in the same tenant →
  403); the per-call **SSRF guard still blocks** loopback/RFC1918/metadata after any allow; the
  allowlist write is tenant-scoped + audited and happens in the backend (no graph node writes the
  DB); the More-info disclosure deep-redacts secret-looking arg keys. Resume:
  `POST /api/v1/chat/{run_id}/resume` with the egress verb + the turn's `provider`. See
  [ADR-0013](docs/architecture/adr/0013-egress-approval-gate.md).
- **Info-panel Activity timeline (#375/#376)**: a reverse-chronological (newest turn on top) unified
  timeline in the info panel that combines each turn's **context snapshot** + **tool calls** (ToolIO)
  + compact **agent-name markers** (Researcher/Planner/Critic/Verify) with UTC timestamps, **filter
  chips** (All / Tools / Reasoning / Context), and a **live** indicator for the in-flight turn. The
  reasoning prose is intentionally **not** in the timeline (it stays in the transcript's per-message
  Details). `GET /api/v1/conversations/{id}` now returns each message's `created_at`.
- **Per-question + per-chat token/time metrics (#368)**: each assistant message persists its token
  usage and latency in `meta.usage` (`prompt_tokens` / `completion_tokens` / `total_tokens` /
  `elapsed_ms`), shown as a **per-message footer** and rolled up into **side-panel chat totals**.
- **Per-question context snapshot (#373)**: the backend persists the prompt-assembly composition into
  the assistant message's `meta.context` (`{items:[{label,count,chars}], total_chars}`); the UI shows
  a per-message **Context (~N tokens)** disclosure via a reusable `ContextComposition` with
  plain-language per-source explanations.
- **Tool I/O progressive disclosure (#372)**: a Tier-1 summary + status pill expands to a Tier-2
  request/response view (copy-full, bounded preview) via new `ToolIO` + `JsonPayload` components;
  context composition is now collapsible with per-source plain-language explanations, and the
  user-question turn is color-coded.
- **Collapsible user questions in the transcript (#379)**: long user questions in the transcript can
  be collapsed/expanded (collapsed shows a short preview), keeping a long thread scannable.

### Changed
- **Draft + attachments survive navigation and reload (#370)**: the composer draft and any attached
  files now persist across in-app navigation **and** a page reload (sessionStorage,
  `personalai_composer_draft`), and Chat no longer unmounts on background session re-validation — so
  switching views or refreshing no longer loses an in-progress message.

### Added
- **Cost + speed on the leaderboard (#330)**: the benchmark leaderboards (HTML + Markdown) now show
  **`$ / run`** and **`tok/s`** next to quality and latency — an artificial-analysis-style view of the
  quality/cost/speed trade-off. Cost comes from token usage × a small **editable** price table
  (`pricing.py`, approximate — prices change); an unpriced model shows "—" (never a guessed number)
  and local PersonalAI shows $0. The tool-equipped frontier adapter now sums token usage across its
  function-calling steps so its cost/speed are accurate.
- **Tool-equipped frontier "chat" variant (#328)**: benchmark frontier models *with tools* (the
  Claude.ai / ChatGPT-style assistant), not just `raw`. `compare --frontier-tools` runs each frontier
  model through a function-calling loop that executes **PersonalAI's own tools** over HTTP
  (`/api/v1/tools` + `/api/v1/tools/invoke`) — so frontier models use the same calculator / web_search
  / MCP tools as PersonalAI (no extra search key), landing in a `frontier_tools` tier next to
  PersonalAI's tool modes. Tool names are sanitized for the model (dotted MCP names → safe names,
  mapped back on invoke). Needs the backend running, like the rest of `compare`.

### Changed
- **Benchmark live progress (#326)**: the `compare`/`run` commands now print a per-attempt line to
  stderr as each one runs — `[ 3/42] openai:gpt-4o · raw · quality_explain_recursion … ok (1240ms)`
  — with a running counter, what's in flight, and the result + latency. A long run (the local model
  across modes + frontier APIs + a judge call per answer) no longer looks frozen.
- **Drag-and-drop images onto the composer (#324)**: attach image(s) for a vision model by dropping
  them onto the message box (a faint "drag & drop images here" hint and a drop-target highlight show
  the affordance). The separate "Image" upload button is removed — drag-drop replaces it. Images
  only, same handling as before (filtered to image/\*, capped at 4, with the not-a-vision-model hint).

### Added
- **Benchmark Phase 2 — frontier contestants + LLM-judge quality (#322)**: M-Bench can now compare
  PersonalAI against **frontier models** on answer **quality**, fairly. One OpenAI-compatible adapter
  reaches OpenAI / Anthropic / DeepSeek / xAI(Grok) / Groq / Gemini (missing keys are skipped). An
  **LLM judge** grades open-ended (rubric) tasks — CoT-then-score, 1–5 per criterion,
  reference-guided, temperature 0, pinned prompt version — with a **self-preference guard**: a
  contestant from the judge's vendor is graded by a fallback judge (Claude→GPT) so a model never
  judges its own family. A multi-system `run_comparison` + `compare` CLI runs everyone over the same
  tasks into one capability-tier leaderboard (rows ranked by quality), never merging cells across
  systems or averaging across tiers. Reports now also render a **styled, self-contained HTML
  leaderboard** (`leaderboard.html`) — color-coded by quality, opens in a browser, prints to PDF —
  alongside the Markdown and JSON. The frontier adapter retries without `temperature` for models
  that reject it (e.g. reasoning models). Pairwise/Bradley-Terry ranking and cost/latency Pareto are
  the planned fast-follow.
- **Benchmark pass@k / repeats (#320)**: the M-Bench runner can now sample each (task, mode) cell
  multiple times (`--repeats N`), so the stochastic noise of local models no longer produces a
  misleading single-sample pass/FAIL. The leaderboard reports **pass@k** (did any attempt solve it —
  capability) alongside **pass-rate** (passed/N — reliability); the per-task matrix shows
  `passes/attempts`, and a Flaky section flags cells that pass some attempts but not all. Default
  `repeats=1` keeps prior behavior.

### Fixed
- **Single-agent tools were enabled but never used (#318)**: the single-agent loop offered tools to
  the model but gave it no instruction to use them, so with reasoning off it answered from "head"
  (e.g. guessing a compound multiplication) instead of calling the calculator — making "single +
  tools" slower *and* less accurate than no-tools. Surfaced by the M-Bench benchmark (single-agent
  made 0 tool calls; multi-agent used tools and scored higher). The single-agent path now injects a
  brief tool-use instruction when tools are enabled (scoped to single mode — the multi-agent
  researcher already has its own). Measured effect: tool-call rate on a compound-arithmetic task went
  from 0% to ~80%, fixing the wrong answers it used to guess.

### Added
- **Agent memory editing + saved dates (#314)**: the agent can now **correct or forget** a memory,
  not just add one. Two new built-in tools — `update_memory` (describe the memory + give the
  correction → the closest match is superseded and the correction stored) and `forget_memory`
  (describe it → the closest match is hidden) — resolve *which* memory by semantic search and act
  deterministically, so "no, it's actually …" / "forget that" replaces or removes instead of piling
  up duplicates. Both are reversible (superseded rows are kept, just hidden) and LOW risk; they
  require tools enabled. The **Memory panel** now shows **when each memory was saved** (and marks
  ones that were later edited).
- **Benchmark harness — M-Bench Phase 1 (#313)**: a new dev-only `benchmarks/` workspace package
  that benchmarks personalIA in multiple configurations and produces a capability-tier leaderboard.
  It drives the backend through a new **`POST /api/v1/assistant/execute`** endpoint — non-streaming,
  one JSON response, with **per-run overrides applied to a config copy that is never persisted** (so
  a run can sweep model / reasoning / agent mode / tools / MCP / RAG / **memory on-off** / grounding
  / max-iterations / accuracy / temperature without mutating saved settings; the human gate is forced
  off). It returns the final answer, trace, tool calls, usage, latency, and the exact `config_used`.
  The harness ships declarative YAML tasks, pluggable scorers (exact / includes / regex / model-graded),
  a runner with reproducibility metadata (git commit, timestamp, platform), JSON + Markdown
  leaderboards grouped by capability tier (never averaged across tiers — memory-on is its own tier),
  and a CLI (`python -m personalai_benchmarks run`). Runs fully local; frontier-model adapters and
  cost/latency-adjusted leaderboards are Phase 2. No new third-party dependency.
- **Memory dedup + conflict reconciliation (#310)**: both memory write paths — the `remember` tool
  and the background extractor — now route every fact through a shared `consolidate_fact()` that
  decides **ADD / UPDATE / NOOP**. A near-duplicate is dropped (no more accumulating copies); a fact
  that **contradicts** an existing memory **supersedes** it and stores the correction (e.g. a changed
  spouse/job/status), instead of leaving two conflicting entries; independent facts are added. The
  decision uses the schema-constrained LLM judge (`generate_structured`) and **fails closed to
  dedup-only** if the judge is unavailable, so it never regresses. New `MemoryStore.supersede()`
  (the `superseded` column was already filtered by search/list). The `remember` tool reports whether
  it added, updated, or found the fact already known.
- **`remember` tool (#308)**: the agent can now **save a fact to long-term memory on request** via a
  new built-in tool (behind the gateway). Previously, asking it to "remember that …" produced a
  confident "Done" with **nothing actually written** — memory was only populated by a separate,
  non-deterministic background extraction. Now "remember this" triggers a real `remember` tool call
  that writes a `MemoryItem` (confidence 1.0, `source=user_request`) and returns its id, so the
  confirmation is grounded in the tool result, shows in the trace, and appears in Settings → Memory
  immediately. Requires tools enabled; the tool is wired once storage is available. (LOW risk, no
  egress.)
- **Read answers aloud (M9.3)**: a **read-aloud** control on each assistant answer, powered by the
  browser's built-in speech synthesis — fully client-side, zero-setup, no new dependencies. Play
  (`▶`) / stop (`■`) monochrome glyphs matching the voice-input controls; one answer reads at a time.
  Gated by a per-tenant **Read answers aloud** setting (Settings → Voice → text-to-speech, on by
  default; `PERSONALAI_TTS_ENABLED`), surfaced via `/status` and only shown when the browser supports
  speech synthesis. First slice of M9.3 — a server-side **Piper** neural-voice provider is the
  planned follow-up. Completes the M9 Multimodal trio (vision · STT · TTS).
- **STT feedback polish (M9.2f)**: the voice composer now keeps you informed instead of waiting
  silently — a live **recording timer** (with a gentle note past 60s), a **"Transcribing…"** state,
  a **no-speech notice** when nothing was heard (common now that silence is filtered out), and a
  hint that the **first transcription downloads the speech model** (which can take a minute) so the
  one-time wait no longer looks like a hang. Microphone failures are now plain-language
  ("Microphone access was blocked…", "No microphone was found…") and an over-long recording reports
  "too long" rather than a raw HTTP error.
- **Spoken-language control for STT (M9.2e)**: a new per-tenant **Spoken language** setting
  (Settings → Voice) — `auto` to auto-detect (multilingual, the default), or pin an ISO-639-1 code
  (`en`/`de`/`es`/`ro`/…). Whisper's auto-detection is probabilistic and can mis-detect the language
  on real-mic audio (e.g. English heard as Bulgarian); pinning forces the right one. Applies to both
  the local and `openai_compat` engines (`PERSONALAI_TRANSCRIBE_LANGUAGE`). Local STT also now runs
  with a **VAD filter** that strips silence/non-speech, which removes phantom phrases on near-silent
  clips and steadies language detection.
- **In-process local Whisper (M9.2c, #300)**: a **zero-setup** speech-to-text engine that runs
  Whisper **in-process** via [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (CTranslate2) — no server, no API key, no egress. Multilingual (auto-detects ~99 languages incl.
  **Romanian**, German, Spanish, English); default model `large-v3-turbo`. The model downloads once
  from Hugging Face, then runs fully offline. This is now the **default** transcribe provider; a new
  `transcribe_provider` per-tenant setting (Settings → Voice → Engine) selects `local` (in-process)
  or `openai_compat` (whisper server / OpenAI). New `personalai-provider-whisper-local` package with
  `LocalWhisperTranscriber` (blocking inference offloaded to a thread, module-level model cache).
- **Speech-to-text (M9.2, #296/#298)**: **voice input**, on by default. A mic button in the
  composer records audio, transcribes it, and drops the text into the composer to review before
  sending. The provider, model, and (for `openai_compat`) endpoint are **per-tenant settings**
  (Settings → Voice). New `Transcriber` port + `OpenAICompatTranscriber` adapter (an OpenAI-compatible
  `/v1/audio/transcriptions` client — point it at a local whisper server or OpenAI), built per-request
  from the tenant's effective config; `POST /api/v1/audio/transcribe`.

### Changed
- **Local Whisper CPU performance (M9.2d)**: `LocalWhisperTranscriber` now uses all CPU cores
  (capped at 8) instead of faster-whisper's slow 4-thread default — roughly halves transcription
  latency for the heavy `large-v3-turbo` model on a multi-core box (e.g. ~9s → ~5s for a few seconds
  of audio). `cpu_threads` is configurable; the model stays loaded across requests (cold load only
  on the first transcription after a restart). Tip: switch the model to `small`/`base` in Settings →
  Voice for near-instant transcription if you don't need turbo-level accuracy.
- **Voice composer countdown (M9.2c/d, #300)**: after the mic stops and the transcript lands in the
  composer, a prominent **3-2-1 countdown** auto-sends it unless you press **Stop** (then the text
  stays editable) — editing also cancels. The mic and send controls are **stacked symbol buttons**
  (mic above send) using monochrome non-emoji glyphs — record `●` / stop `■` (red, the record
  convention) / transcribing `…`, send `↑` — with the description in the tooltip/aria-label and an
  `aria-live` status for screen readers.
- **Settings placeholders (M9.2e)**: text fields whose deployment default is blank (e.g. the
  `openai_compat` "Whisper server URL") now show a descriptive placeholder ("blank = OpenAI base
  URL") instead of an empty box that looked unset.
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

[Unreleased]: https://github.com/lucianhanga/personal-ai/compare/v0.8.3...HEAD
[0.8.3]: https://github.com/lucianhanga/personal-ai/compare/v0.7.0...v0.8.3
[0.7.0]: https://github.com/lucianhanga/personal-ai/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/lucianhanga/personal-ai/releases/tag/v0.6.0
