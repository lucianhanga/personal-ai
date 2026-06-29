# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/) and the project follows
[Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

**Versioning policy (pre-1.0):** `MAJOR` stays `0` until the first stable release; `MINOR` bumps as
each milestone (M1, M2, …) lands; `PATCH` bumps for fixes/UX tweaks between milestones. The HTTP API
is versioned independently in the URL path (`/api/v1`) and surfaced as `info.version` in the
generated OpenAPI document.

## [Unreleased]

## [0.9.0] — 2026-06-29

Milestone **M11 (knowledge graph / KAG)** — the entity knowledge graph over your corpus — brought
forward ahead of M10, together with **Documents v2** (on-device OCR + continuously-synced local
folders), **multi-source RAG** (a planner-chosen set of retrieval sources fused into one evidence
set), and a **multi-agent redesign** (a tool-armed judge fact-check + evaluator-optimizer
re-planning). The MV3 browser extension (M10) remains next.

> Scope note: this is the **first** delivery of M11. It ships a relational entity store
> (`entities` / `entity_documents` / `entity_edges`) populated by local LLM-NER over the document
> corpus — not the originally-sketched Apache AGE graph, and not yet a graph upgrade of long-term
> memory. See [ADR-0014](docs/architecture/adr/0014-kag-entity-store.md).

### Added
- **Knowledge graph (KAG) over your corpus (#451)**: a new entity store (`entities`,
  `entity_documents`, `entity_edges`) populated by **local LLM named-entity extraction** wired into
  global document ingest. Extraction is corpus-global (an entity can span many documents/folders),
  windowed over the whole document, and never reaches the network. Documents attached to a single
  chat are not added to the graph. See [ADR-0014](docs/architecture/adr/0014-kag-entity-store.md) and
  [Documents & folders](docs/guides/documents-and-folders.md#5-the-knowledge-graph-entities).
- **Dedicated NER model + memory-aware admission (#469, #470)**: entity extraction runs on its own
  small, fast local model (`ner_model`, `PERSONALAI_NER_MODEL`) at a small context window; before
  loading it the app checks the **global** Ollama load against `ner_memory_fraction` and **defers**
  rather than evict a resident model. The window is **model-aware** (large for dense models, small
  for the MoE). A deterministic junk filter drops IBANs/BICs/codes the local model mislabels (#464),
  and post-NER **entity resolution** merges near-duplicate names conservatively (#477).
- **Multi-source retrieval (#420, #442)**: a `RetrievalSource` seam — the planner emits a
  `SourcePlan`, two LangGraph nodes (`gather`, `merge`) fan out over the chosen sources in bounded
  parallel and fuse the results with **cross-source RRF** + a per-source token budget, and the
  answer carries **unified citations** tagged with `source_kind` / `merged_from`. With no sources the
  graph topology is unchanged.
- **Hybrid (dense + lexical) scoped retrieval (#435)**: vector RAG retrieval now fuses dense and
  lexical matches with Reciprocal Rank Fusion (via `langchain-core`) before the cross-source merge.
- **Conversation-scoped RAG for large attachments (#438) + eager ingest-at-attach (#420)**: a large
  document is indexed into the conversation's own RAG scope and retrieved (with citations) instead of
  being dumped into the prompt; the indexing now happens **when the file is attached**, not on send,
  so the first large-doc turn is not slow. Small documents still fold inline behind a token gate
  (#422).
- **KAG aggregation source — answer "how many X" (#475)**: an enumeration source over the entity
  graph that counts/enumerates entities of a type, with name resolution so a query phrase resolves to
  stored entities (#476).
- **Settings → Knowledge — graph + corpus explorer (#471, #473, #474, #483, #485, #487)**: a new
  **Knowledge** settings section (between Memory and Network) with a **KAG graph** tab and a **RAG
  corpus** tab — an entity browser (grouped by type, name search), a **co-occurrence** toggle, a
  **chunk inspector**, deep-links, a **Retrieval Explorer**, a full-corpus view, on-canvas labels,
  Fit/Reset, a legend, a Top-entities launcher, and corpus columns (Type / Size / Entities, with
  sort / search / status filter and stat cards). Exact entity counts come from a new
  `GET /api/v1/entities/stats` plus a per-document `entity_count` (#485).
- **On-device OCR for scanned PDFs (#450)**: a scanned / image-only PDF (no text layer) is rendered
  and read with **RapidOCR** (PaddleOCR models via ONNX Runtime) so it becomes searchable like any
  other document — fully offline. A PDF with no recoverable text reports "no text found" rather than
  failing.
- **Continuously-synced folder sources (#456, #458)**: point Settings → Documents at a local folder
  (by absolute path, validated server-side) and the backend keeps it indexed as files are added /
  changed / deleted — a native filesystem watcher (`watchdog`), a periodic safety-net scan, and a
  startup reconcile, with the database as the source of truth. New schema (`folder_sources`,
  `folder_files`, `documents.manual_pin`), `GET`/`POST /api/v1/folders` (+ detail / delete / resync /
  pause / resume) and a live `events` SSE, plus a folder UI (status cards, a nested directory tree,
  file drill-down). The sync is **fail-closed to local providers** — it never sends a document off
  device. See [Documents & folders](docs/guides/documents-and-folders.md).
- **Tool-armed judge fact-check (#479, #482, #489)**: in the multi-agent graph the final answer is
  fact-checked against **fresh, independently-gathered** ground truth — the verifier (accurate mode)
  and the critic (when it is the last judge, in standard mode) run a bounded independent RAG/KAG/memory
  **retrieval lookup** PLUS a **verify-only tool pass** (a tiny run with the researcher's web/MCP
  tools, prompted to confirm/refute the draft's claims — not re-research), so even tool/web-derived
  answers get checked, not only source-grounded ones. Both halves are fail-open; exactly one judge
  runs them per turn.
- **Evaluator-optimizer re-planning (#484)**: the critic can return a `replan` verdict that routes
  back to the **planner** (the plan itself was the fault → re-plan + re-retrieve), distinct from
  `revise` (sound plan, poor execution → back to the researcher). Both share the bounded
  `MAX_ATTEMPTS` budget so the loop stays bounded.
- **Source-agnostic agents + a configurable verifier (#481)**: the default agent prompts are now
  generic (not tied to a specific source), and the **verifier** is promoted to a first-class,
  tenant-overridable agent with its own distinct trace color — joining planner / researcher / critic
  in **Settings → Agents**.
- **Live agent collaboration graph (#482)**: Settings → Agents shows a diagram of how the configured
  agents collaborate, redrawn for the selected agentic design (single / multi / accurate).
- **Document-pipeline visibility in the Activity timeline (#439, #450, #462)**: the
  indexing / retrieval / NER pipeline (OCR → extract → vectorize → index) is surfaced as Activity
  events, the planner now **streams**, and universal **stage heartbeats** plus live retrieval
  progress mean a long turn never reads as frozen (#465).
- **Stop button + message management (#412, #441)**: stop an in-flight answer, and **copy / edit /
  delete** chat messages.
- **Multimodal attachments (#421, #422, #430, #408, #405)**: attach **images** (downscaled, eagerly
  described, hover/copy), **documents** (inline-fold or RAG by size), and **audio** (drag-drop chips
  with a hover transcript panel; upload → transcript → **one-tap summarize**); sent-message
  attachments render as prompt + hover chips rather than folded text.
- **Configurable web_search providers (#407)**: choose **DuckDuckGo**, **SearXNG**, or **Tavily** for
  the built-in `web_search` tool.
- **Runaway-generation guard (#415)**: sampling penalties, an output cap, and a repetition watchdog
  stop a local model from looping forever.
- **One-command bootstrap — `make dev` (#413)**: a single command checks tooling, installs deps,
  starts the database, and runs the backend + UI together.
- **NER extraction playground (#464, #468)**: a dev-only `tools/test` harness to compare Ollama vs
  OpenAI named-entity extraction (live per-window progress, token usage, configurable model/context).

### Changed
- **Multi-agent graph topology**: the graph is now
  `planner → [gather → merge →] researcher → [egress_gate →] critic → [verifier →] [human_gate] →
  finalize`, with the critic routing `replan → planner` / `revise → researcher`. The critic and
  verifier judge against the **fused multi-source evidence**, preserved in a distinct state key so a
  researcher answer that doesn't re-call tools can't clobber it (#480).
- **3-section app shell (#486)**: the title and the status bar are **pinned**; only the conversation
  body scrolls.
- **Honest scanned-PDF empty state (#446)**: an attached PDF with no embedded text explains the
  situation (and that OCR runs on the durable-ingest path) instead of silently producing nothing.
- **413 handling**: oversize uploads now return `HTTP_413_CONTENT_TOO_LARGE` (Starlette deprecation).

### Fixed
- **The "unknown tool" denial is now actionable (#488)**: a call to an unregistered tool returns a
  gateway denial that **suggests the closest registered name** instead of a bare rejection.
- **Merged multi-source evidence is no longer clobbered before the critic/verifier judged (#480)**.
- **The planner no longer refuses private-data questions (#478)**: it is taught that the researcher
  has RAG / KAG / memory, so it stops declining "what do my documents say…" questions.
- **The KAG count source resolves entity phrases (#476)**: a query like "M-Net invoices" that matched
  nothing now resolves to the stored entities.
- **Structured-output repair hardening (#443, #444)**: a non-dict `invalid_payload` no longer crashes
  the repair path; MoE structured output omits `think` so the `format` constraint is honored.
- **An earlier question's image no longer leaks onto a later turn (#400)**.
- **The KAG is never wiped on a failed extraction (#466)**: a failed NER run leaves the existing graph
  intact (the document stays searchable; it is just not added to the graph), with a configurable
  Ollama timeout.
- **Embed query length is bounded (#432)** so a folded document can't overflow the embedding input.
- **Folder-synced files no longer appear under Individual uploads (#451)**.

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

[Unreleased]: https://github.com/lucianhanga/personal-ai/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/lucianhanga/personal-ai/compare/v0.8.3...v0.9.0
[0.8.3]: https://github.com/lucianhanga/personal-ai/compare/v0.7.0...v0.8.3
[0.7.0]: https://github.com/lucianhanga/personal-ai/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/lucianhanga/personal-ai/releases/tag/v0.6.0
