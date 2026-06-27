/** Client for the local PersonalAI backend. */

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8765";

export interface ModelCapabilities {
  text: boolean;
  vision: boolean;
  embeddings: boolean;
  tool_calling: boolean;
  structured_output: boolean;
  thinking: boolean;
  max_context_tokens: number | null;
}

export interface ModelInfo {
  name: string;
  local: boolean;
  capabilities: ModelCapabilities;
}

// Ordered step in an assistant turn's timeline. The single-agent loop emits reasoning/tool_call/
// tool_result; M8 (ADR-0011) adds multi-agent + verification kinds (plan/critique/verification). The
// UI renders unknown kinds generically, so adding kinds server-side never breaks an older client.
export interface TraceItem {
  kind:
    | "reasoning"
    | "tool_call"
    | "tool_result"
    | "plan"
    | "critique"
    | "verification"
    | "draft"
    | "resource" // #424 — eager resource-processing (image/doc/audio), a strict superset of the above
    | "indexing" // #437 — a large doc chunked+embedded into the conversation scope (RAG prelude)
    | "retrieval" // #437 — the hybrid query that assembled context (query/hits/scope/citations)
    | "ner" // #437 — entity extraction (DORMANT until Phase 6; renderer ignores an absent ner)
    | "stage"; // #465 — a transient node-entry "working" heartbeat (planning/researching/...), live
  text?: string;
  role?: string | null; // which agent produced it (researcher/critic/verifier) — M8
  verdict?: string | null; // verification outcome (e.g. "pass"/"fail"/"needs-revision") — M8
  tool?: string | null;
  args?: Record<string, unknown> | null;
  ok?: boolean | null;
  output?: Record<string, unknown> | null;
  error?: string | null;
  ts?: string; // wall-clock UTC ISO when this step happened (per-step time in the activity timeline)
  attempt?: number; // which researcher pass produced a `draft` answer (#393)
  // Resource-activity fields (#424; kind === "resource"). The renderer keys off `action` + `status`.
  action?: ResourceAction;
  ref?: string; // resource name/id (filename) — ties the item to its attachment
  model?: string | null; // model id; null/absent for non-model work (document parse)
  ms?: number | null; // wall-clock duration of the eager call
  status?: string | null; // "ok" (default) | "error"
  // RAG-pipeline prelude fields (#437). All additive; absent on legacy/non-RAG turns. `indexing`
  // reuses `ref`/`ms`/`status`/`error` above and adds `chunks`; `retrieval`/`ner` add the below.
  chunks?: number; // indexing — how many chunks the doc was split into
  query?: string; // retrieval — the standalone hybrid query (clipped server-side)
  top_k?: number; // retrieval — the requested top-k
  hits?: number; // retrieval — passages returned (0 is a deliberate "searched, found nothing")
  scope?: "global" | "conversation" | "union"; // retrieval — which corpus was searched
  citations?: { source: string; score: number }[]; // retrieval — compact winners-only list (<=8)
  count?: number; // ner — entities extracted (Phase 6)
  types?: { type: string; count: number }[]; // ner — per-type breakdown (Phase 6)
  // Live retrieval progress (#462). The graph's gather node streams a transient running -> done
  // `retrieval` frame during the planner->researcher gap (status: "running" then "ok"); `live`
  // marks it stream-only (superseded in place, never persisted). `sources`/`counts` describe the
  // multi-source fan-out (e.g. {"vector": 4, "memory": 2}). `source_kind` tags the durable
  // per-source items (#420) so the live frame and the persisted ones never collide.
  sources?: string[]; // retrieval (live) — the source kinds being queried, in plan order
  counts?: Record<string, number>; // retrieval (live, done) — hits per source kind
  source_kind?: string; // retrieval (persisted, per-source) — which source kind this item is for
  live?: boolean; // retrieval/stage — true for a transient progress frame (superseded, not persisted)
  // Generic stage heartbeat (#465; kind === "stage"). Emitted at each graph node's entry so the UI
  // always shows progress and a busy/model-waiting node never reads as blocked. `name` is the node
  // ("planner"/"researcher"/...); `label` is the human caption ("Planning"/"Researching"/...).
  name?: string; // stage — the graph node id
  label?: string; // stage — the human-readable caption shown in the live indicator
}

// The architect's closed resource-action enum (#424). Extend only by adding a member here AND in the
// backend `_ACTIVITY_ACTIONS` allowlist, or new actions are silently dropped at the persist boundary.
// #424 base actions + the #450 document-pipeline stages (OCR -> extract -> vectorize -> index),
// each surfaced as a resource activity so the user sees the full prep pipeline for an attachment.
export type ResourceAction =
  | "image_described"
  | "document_extracted"
  | "document_ocred"
  | "document_vectorized"
  | "document_indexed"
  | "audio_transcribed";

/** A pre-turn resource-processing activity (#424): image describe / document extract / audio
 * transcribe. Buffered client-side as the user prepares a message, then persisted on the user turn's
 * `meta["activities"]`. A strict superset of {kind,text,ts} so one renderer covers trace + resource. */
export interface ResourceActivity {
  kind: "resource";
  action: ResourceAction;
  text: string; // human label, e.g. "Described image — cat.jpg"
  ref: string; // resource name/id (filename)
  ts: number; // UTC seconds (the persist boundary clamps far-future/garbage)
  model?: string | null; // model id (image/audio/embed); null for document parse
  ms?: number | null; // eager-call wall-clock in ms
  note?: string | null; // #450: per-stage meta detail, e.g. "35 pages" / "50 chunks" / "this chat"
  status?: "ok" | "error"; // defaults to "ok"
  error?: string | null; // message when status === "error"
}

/** A durable human-gate approval request (M8.1c): the run is suspended until POST .../resume.
 * The answer gate sends reason:"approve_answer" with answer/critique; the egress gate (#377) sends
 * reason:"egress_approval" with the blocked_host + the outbound tool/args the run wants to make. */
export interface ApprovalRequest {
  run_id: string;
  reason?: string;
  answer?: string;
  critique?: string;
  // Egress gate (reason:"egress_approval"): the non-allowlisted host the run paused on, plus the
  // tool + args of the outbound call so the user can see exactly what would be sent before deciding.
  blocked_host?: string;
  tool?: string;
  args?: Record<string, unknown>;
}

// The human's decision when resuming a suspended run. The answer gate uses approve/reject; the
// egress gate (#377) uses one of the egress_* verbs (allow once / allow + remember / deny).
export type ResumeDecision =
  | "approve"
  | "reject"
  | "egress_allow_once"
  | "egress_allow_always"
  | "egress_deny";

// Per-assistant-turn token + time metrics, persisted so they survive a reload.
export interface TurnUsage {
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  elapsed_ms: number | null;
}

export interface MessageMeta {
  // Ordered timeline of reasoning + tool steps (new format).
  trace?: TraceItem[];
  // Token + time metrics for this turn (shown as a per-message footer; summed into chat totals).
  usage?: TurnUsage;
  // Per-question context snapshot (same shape as the live `context` SSE event), so each past
  // assistant turn can show "what was in the context window" — see the per-message disclosure.
  context?: ContextBreakdown;
  // User-driven Stop (#412): set on an assistant turn that the user halted mid-generation. Persisted
  // distinct from the red `error` path so the transcript frames it as an intentional stop (amber
  // "Generation stopped." marker), not a failure. Absent on completed turns.
  stopped?: { by: string; ts?: string };
  // Legacy (pre-ordered-trace) fields, kept for older persisted messages.
  tool_steps?: ToolStep[];
  thinking?: string;
}

export interface ChatMessage {
  // Stable per-message id (#441): the global monotonic `messages.id` from the backend, surfaced by
  // get_conversation. The cursor for truncate-from-turn (Edit/Delete) and the Copy buffer. Absent on
  // the in-flight (optimistic) turn that hasn't been persisted yet — Edit/Delete are disabled there.
  id?: number;
  role: "system" | "user" | "assistant";
  content: string;
  // Attached image parts as data-URLs (data:image/...;base64,...) for vision models (M9.1).
  images?: string[];
  // Parallel to `images`: an eager vision description per image (#419), shown on hover + persisted.
  // Request-only metadata (not sent to the model — vision models get the image itself).
  image_descriptions?: string[];
  // Pre-turn resource-processing activities (#424): buffered as the user prepares the message, then
  // persisted on the user turn and surfaced top-level on reload so the Activity timeline re-renders
  // them. Request-only metadata (sanitized server-side; not sent to the model). Empty for old turns.
  activities?: ResourceActivity[];
  // Sent-message attachment presentation (#426): the display-vs-model split. `content` stays the
  // folded model-facing string; these carry the structured display data so the transcript renders
  // the user's original prompt + attachment chips instead of the folded text. Request-only (mapped
  // to snake_case for the backend, sanitized + persisted in the user turn's meta). Absent/empty for
  // old turns, which fall back to rendering `content` verbatim.
  //   - displayContent: the user's original typed prompt (pre-fold), shown as the bubble body.
  //   - documents: one {name, text} per sent document chip; reveals the extracted text on hover.
  //   - audio: one {name, transcript} per sent audio chip; reveals the transcript on hover.
  displayContent?: string;
  documents?: { name: string; text: string }[];
  audio?: { name: string; transcript: string }[];
  // Tier-2 ingest-at-send (#436, RAG epic #420): the FULL extracted text of LARGE docs (over the
  // inline gate). The backend chunks+embeds these into the conversation-scoped RAG index BEFORE
  // retrieval and answers from them with citations. Request-only; snake_case already matches the
  // backend field, so it passes through wireMessages unchanged. Absent when no large doc is attached.
  documents_full?: { name: string; text: string }[];
  // Persisted per-assistant-message detail (tool calls + reasoning), shown collapsed in the UI.
  meta?: MessageMeta | null;
  // ISO timestamp set when the message was persisted (GET /conversations/{id}); absent for the
  // in-flight (live) message that hasn't been written yet — the timeline treats that as "now".
  created_at?: string;
}

export interface DocumentInfo {
  id: string;
  name: string;
  mime: string;
  size_bytes: number;
  chunk_count: number;
  created_at: string;
}

export interface Citation {
  n: number;
  source_id: string;
  locator: string | null;
  score: number;
  name: string | null;
  // #420 multi-source provenance (optional, additive): which source a citation came from
  // ("vector" | "memory" | "graph" | "tool:..."), and the other source kinds a deduped citation
  // also appeared in. Absent on single-source (standard, tools-off) turns predating multi-source.
  source_kind?: string;
  merged_from?: string[];
}

export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
}

export interface MemoryItem {
  id: string;
  kind: string;
  text: string;
  confidence: number;
  source: Record<string, string>;
  created_at: string;
  updated_at: string;
}

export interface ToolPermission {
  type: string;
  scope: string;
}

export interface ToolInfo {
  name: string;
  version: string;
  risk: string;
  capabilities: string[];
  permissions: ToolPermission[];
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
}

export interface ToolInvokeResult {
  ok: boolean;
  data?: Record<string, unknown>;
  error?: string;
}

export interface ToolStep {
  phase: "call" | "result";
  tool: string;
  args?: Record<string, unknown> | null;
  ok?: boolean | null;
  output?: Record<string, unknown> | null;
  error?: string | null;
  ts?: string; // wall-clock UTC ISO when the call/result happened (per-step timeline time)
}

export interface ToolLogEntry {
  index: number;
  type: string; // "tool.invoke" | "tool.denied"
  timestamp: string;
  tool: string | null;
  ok?: boolean | null;
  error?: string | null;
  args?: Record<string, unknown> | null;
}

export interface LogEntry {
  time: string;
  level: string;
  logger: string;
  message: string;
}

export interface UsageInfo {
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  context_limit: number | null;
  elapsed_ms: number | null; // wall-clock time for this turn (per-question + per-chat timing)
}

// What was assembled into the model's context this turn (grounding, documents, memory, ...), so the
// user can see the composition and approximate size as the question is asked.
export interface ContextItem {
  label: string;
  count: number;
  chars: number;
  // The source's assembled text (capped backend-side), for the in-browser token visualization
  // (#391). Absent for turns persisted before this field existed.
  text?: string;
}

export interface ContextBreakdown {
  items: ContextItem[];
  total_chars: number;
}

export interface McpServer {
  name: string;
  command: string;
  args: string[];
  env: Record<string, string>;
  enabled: boolean;
  connected: boolean;
  tools: string[];
  error: string | null;
}

export interface McpServerInput {
  command: string;
  args: string[];
  env: Record<string, string>;
  enabled: boolean;
}

export type McpHealthStatus = "healthy" | "unreachable" | "error" | "disabled";

export interface McpHealth {
  name: string;
  status: McpHealthStatus;
  latency_ms: number | null;
  tool_count: number | null;
  error: string | null;
  checked_at: string;
}

/** The whole mcpServers map (env masked) for the JSON editor / export. */
export type McpConfig = Record<string, McpServerInput>;

function readCookie(name: string): string {
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : "";
}

// Auth headers for every request: the legacy bearer token (local/dev) plus the double-submit CSRF
// token (hosted cookie sessions). Both are harmless when unused — the backend resolves cookie
// sessions first, then the bearer; CSRF is only checked for cookie-authenticated unsafe requests.
function authHeaders(token: string): Record<string, string> {
  const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
  const csrf = readCookie("pai_csrf");
  if (csrf) headers["X-CSRF-Token"] = csrf;
  return headers;
}

// All authenticated requests send credentials so the session cookie rides cross-origin (hosted SPA).
const CREDS: RequestCredentials = "include";

export interface SessionInfo {
  subject_id: string;
  tenant_id: string;
  auth_kind: string;
}

/** Current session (dev/cookie/api-key), or null when unauthenticated (hosted, not logged in). */
export async function fetchSession(token: string): Promise<SessionInfo | null> {
  const res = await fetch(`${API_BASE}/api/v1/auth/session/me`, {
    headers: authHeaders(token),
    credentials: CREDS,
  });
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`session request failed: ${res.status}`);
  return ((await res.json()) as { data?: SessionInfo }).data ?? null;
}

/** Log in with email + password (hosted mode); sets the session + CSRF cookies. */
export async function login(email: string, password: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: CREDS,
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error("invalid credentials");
}

/** Create an account (hosted mode). Always succeeds silently (no user enumeration). */
export async function signup(email: string, password: string): Promise<void> {
  await fetch(`${API_BASE}/api/v1/auth/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: CREDS,
    body: JSON.stringify({ email, password }),
  });
}

/** Log out: revoke the session and clear cookies. */
export async function logout(token: string): Promise<void> {
  await fetch(`${API_BASE}/api/v1/auth/logout`, {
    method: "POST",
    headers: authHeaders(token),
    credentials: CREDS,
  });
}

/** Returns true if the backend /health endpoint reports ok. Never throws. */
export async function fetchHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) return false;
    const body = (await res.json()) as { status?: string };
    return body.status === "ok";
  } catch {
    return false;
  }
}

/** List the registered providers and the default one. */
export async function fetchProviders(
  token: string,
): Promise<{ default: string; providers: string[] }> {
  const res = await fetch(`${API_BASE}/api/v1/providers`, { headers: authHeaders(token), credentials: CREDS });
  if (!res.ok) throw new Error(`providers request failed: ${res.status}`);
  const body = (await res.json()) as { data?: { default?: string; providers?: string[] } };
  return { default: body.data?.default ?? "", providers: body.data?.providers ?? [] };
}

/** List a provider's models (with capabilities) and the default model. */
export async function fetchModels(
  token: string,
  provider?: string,
): Promise<{ defaultModel: string; models: ModelInfo[] }> {
  const url = new URL(`${API_BASE}/api/v1/models`);
  if (provider) url.searchParams.set("provider", provider);
  const res = await fetch(url, { headers: authHeaders(token), credentials: CREDS });
  if (!res.ok) throw new Error(`models request failed: ${res.status}`);
  const body = (await res.json()) as {
    ok?: boolean;
    error?: { message?: string };
    data?: { default_model?: string; models?: ModelInfo[] };
  };
  if (body.ok === false) throw new Error(body.error?.message ?? "models request failed");
  return { defaultModel: body.data?.default_model ?? "", models: body.data?.models ?? [] };
}

/** Upload a file for ingestion. Returns the created document (or throws on a structured error). */
export async function uploadFile(token: string, file: File): Promise<DocumentInfo> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/v1/files`, {
    method: "POST",
    headers: authHeaders(token),
    credentials: CREDS,
    body: form,
  });
  if (!res.ok) throw new Error(`upload failed: ${res.status}`);
  const body = (await res.json()) as {
    ok?: boolean;
    error?: { message?: string };
    data?: DocumentInfo;
  };
  if (body.ok === false || !body.data) throw new Error(body.error?.message ?? "upload failed");
  return body.data;
}

/** Whether the backend has speech-to-text configured (so the UI shows the mic) — M9.2. */
export async function fetchTranscribeEnabled(token: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/status`, {
      headers: authHeaders(token),
      credentials: CREDS,
    });
    if (!res.ok) return false;
    const body = (await res.json()) as { data?: { transcribe_enabled?: boolean } };
    return body.data?.transcribe_enabled === true;
  } catch {
    return false;
  }
}

/** Whether reading answers aloud is enabled (so the UI shows the read-aloud control) — M9.3. */
export async function fetchTtsEnabled(token: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/status`, {
      headers: authHeaders(token),
      credentials: CREDS,
    });
    if (!res.ok) return false;
    const body = (await res.json()) as { data?: { tts_enabled?: boolean } };
    return body.data?.tts_enabled === true;
  } catch {
    return false;
  }
}

/** Transcribe a recorded audio blob (mic) or an uploaded audio file to text via the backend
 * transcriber (M9.2). When `filename` is given (file upload), it is sent as the form filename so the
 * backend sees the real name + content-type; the mic caller omits it and keeps "recording.webm". */
// Result of an eager resource-processing call (#424): the facts the UI assembles a resource activity
// from. `model`/`ms` are surfaced by the endpoints additively (model null for the document parse).
export interface TranscribeResult {
  text: string;
  model: string | null;
  ms: number | null;
}

export async function transcribeAudio(
  token: string,
  audio: Blob,
  filename = "recording.webm",
  signal?: AbortSignal,
): Promise<TranscribeResult> {
  const form = new FormData();
  form.append("file", audio, filename);
  const res = await fetch(`${API_BASE}/api/v1/audio/transcribe`, {
    method: "POST",
    headers: authHeaders(token),
    credentials: CREDS,
    body: form,
    signal,
  });
  if (!res.ok) throw new Error(`transcribe failed: ${res.status}`);
  const body = (await res.json()) as {
    ok?: boolean;
    error?: { message?: string };
    data?: { text?: string; model?: string | null; ms?: number | null };
  };
  if (body.ok === false) throw new Error(body.error?.message ?? "transcribe failed");
  return {
    text: body.data?.text ?? "",
    model: body.data?.model ?? null,
    ms: body.data?.ms ?? null,
  };
}

// Result of the eager image-describe call (#424).
export interface DescribeResult {
  description: string;
  model: string | null;
  ms: number | null;
}

/** Describe an attached image with the vision model (#419) — eager caption shown on hover + stored.
 * `image` is the (already-downsized) image blob. Throws on transport/HTTP error or a structured
 * error (e.g. `E_NO_VISION_MODEL`). Returns the description plus the model + wall-clock (#424). */
export async function describeImage(
  token: string,
  image: Blob,
  signal?: AbortSignal,
): Promise<DescribeResult> {
  const form = new FormData();
  form.append("file", image, "image.jpg");
  const res = await fetch(`${API_BASE}/api/v1/images/describe`, {
    method: "POST",
    headers: authHeaders(token),
    credentials: CREDS,
    body: form,
    signal,
  });
  if (!res.ok) throw new Error(`describe failed: ${res.status}`);
  const body = (await res.json()) as {
    ok?: boolean;
    error?: { message?: string };
    data?: { description?: string; model?: string | null; ms?: number | null };
  };
  if (body.ok === false) throw new Error(body.error?.message ?? "describe failed");
  return {
    description: body.data?.description ?? "",
    model: body.data?.model ?? null,
    ms: body.data?.ms ?? null,
  };
}

export interface ExtractedDocument {
  name: string;
  mime: string;
  text: string;
  truncated: boolean;
  // #424: document extraction is a local CPU parse — `model` is always null; `ms` is the parse
  // wall-clock so the resource activity can still show a duration. Optional for back-compat.
  model?: string | null;
  ms?: number | null;
  // #450: `ocr` is true when the text came from the OCR fallback (a scanned / image-only PDF) and
  // `pages` is the PDF page count — so the pipeline activity can show a truthful "OCR'd N pages" step.
  ocr?: boolean;
  pages?: number | null;
}

/** Extract text from an uploaded document (PDF/DOCX/txt/md) for a per-question attachment (#416).
 * No storage/vectorization — small docs are folded into the message; large ones are gated (#420). */
export async function extractDocument(
  token: string,
  file: File,
  signal?: AbortSignal,
): Promise<ExtractedDocument> {
  const form = new FormData();
  form.append("file", file, file.name);
  const res = await fetch(`${API_BASE}/api/v1/files/extract`, {
    method: "POST",
    headers: authHeaders(token),
    credentials: CREDS,
    body: form,
    signal,
  });
  if (!res.ok) throw new Error(`extract failed: ${res.status}`);
  const body = (await res.json()) as {
    ok?: boolean;
    error?: { message?: string };
    data?: ExtractedDocument;
  };
  if (body.ok === false || !body.data) throw new Error(body.error?.message ?? "extract failed");
  return body.data;
}

/** List ingested documents. */
export async function fetchFiles(
  token: string,
  opts?: { includeSynced?: boolean },
): Promise<DocumentInfo[]> {
  // Default: manual uploads only ("Individual uploads"). includeSynced=true returns the FULL global
  // corpus (manual + folder-synced) for the Knowledge -> Corpus overview (#465).
  const qs = opts?.includeSynced ? "?include_synced=true" : "";
  const res = await fetch(`${API_BASE}/api/v1/files${qs}`, {
    headers: authHeaders(token),
    credentials: CREDS,
  });
  if (!res.ok) throw new Error(`files request failed: ${res.status}`);
  const body = (await res.json()) as { data?: { files?: DocumentInfo[] } };
  return body.data?.files ?? [];
}

/** Delete an ingested document. */
export async function deleteFile(token: string, id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/files/${id}`, {
    method: "DELETE",
    headers: authHeaders(token),
    credentials: CREDS,
  });
  if (!res.ok) throw new Error(`delete failed: ${res.status}`);
}

/** Create a new conversation (optionally incognito = no long-term memory writes). */
export async function createConversation(
  token: string,
  title?: string,
  incognito = false,
): Promise<ConversationSummary> {
  const res = await fetch(`${API_BASE}/api/v1/conversations`, {
    method: "POST",
    credentials: CREDS,
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ title, incognito }),
  });
  if (!res.ok) throw new Error(`create conversation failed: ${res.status}`);
  const body = (await res.json()) as { data?: ConversationSummary };
  if (!body.data) throw new Error("create conversation failed");
  return body.data;
}

/**
 * Tier-2 ingest-at-attach (#420): eagerly chunk+embed a large attachment into a conversation's RAG
 * scope when it is attached, before any question is sent — so it is searchable immediately. The
 * backend is idempotent by content-hash, so the later ingest-at-send for the same doc skips.
 */
export interface IngestedDocument {
  document_id: string;
  chunk_count: number | null;
  already_indexed: boolean;
  embed_model?: string | null; // #450: embedding model, for the "Vectorized" pipeline activity
  ms?: number | null; // #450: chunk+embed wall-clock
}

export async function ingestConversationDocument(
  token: string,
  conversationId: string,
  name: string,
  text: string,
): Promise<IngestedDocument> {
  const res = await fetch(`${API_BASE}/api/v1/conversations/${conversationId}/documents`, {
    method: "POST",
    credentials: CREDS,
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ name, text }),
  });
  if (!res.ok) throw new Error(`document ingest failed: ${res.status}`);
  const body = (await res.json()) as {
    ok?: boolean;
    data?: IngestedDocument;
    error?: { message?: string };
  };
  if (!body.ok || !body.data) throw new Error(body.error?.message ?? "document ingest failed");
  return body.data;
}

/** List long-term memories. */
export async function fetchMemories(token: string): Promise<MemoryItem[]> {
  const res = await fetch(`${API_BASE}/api/v1/memory`, { headers: authHeaders(token), credentials: CREDS });
  if (!res.ok) throw new Error(`memory request failed: ${res.status}`);
  const body = (await res.json()) as { data?: { memories?: MemoryItem[] } };
  return body.data?.memories ?? [];
}

/** Edit a memory's text. */
export async function updateMemory(token: string, id: string, text: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/memory/${id}`, {
    method: "PATCH",
    credentials: CREDS,
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error(`update memory failed: ${res.status}`);
}

/** Delete a single memory. */
export async function deleteMemory(token: string, id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/memory/${id}`, {
    method: "DELETE",
    headers: authHeaders(token),
    credentials: CREDS,
  });
  if (!res.ok) throw new Error(`delete memory failed: ${res.status}`);
}

/** Forget everything (delete all memories). */
export async function forgetAllMemory(token: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/memory`, {
    method: "DELETE",
    headers: authHeaders(token),
    credentials: CREDS,
  });
  if (!res.ok) throw new Error(`forget all failed: ${res.status}`);
}

/** List the tools registered behind the gateway. */
export async function fetchTools(token: string): Promise<ToolInfo[]> {
  const res = await fetch(`${API_BASE}/api/v1/tools`, { headers: authHeaders(token), credentials: CREDS });
  if (!res.ok) throw new Error(`tools request failed: ${res.status}`);
  const body = (await res.json()) as { data?: { tools?: ToolInfo[] } };
  return body.data?.tools ?? [];
}

const convQuery = (conversationId?: string | null): string =>
  conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : "";

/** Recent application/server logs (most recent first), optionally scoped to a conversation. */
export async function fetchLogs(token: string, conversationId?: string | null): Promise<LogEntry[]> {
  const res = await fetch(`${API_BASE}/api/v1/logs${convQuery(conversationId)}`, {
    headers: authHeaders(token),
    credentials: CREDS,
  });
  if (!res.ok) throw new Error(`logs request failed: ${res.status}`);
  const body = (await res.json()) as { data?: { logs?: LogEntry[] } };
  return body.data?.logs ?? [];
}

/** Configured MCP servers + connect status + the tools each exposed. */
export async function fetchMcp(token: string): Promise<McpServer[]> {
  const res = await fetch(`${API_BASE}/api/v1/mcp`, { headers: authHeaders(token), credentials: CREDS });
  if (!res.ok) throw new Error(`mcp request failed: ${res.status}`);
  const body = (await res.json()) as { data?: { servers?: McpServer[] } };
  return body.data?.servers ?? [];
}

/** Create or update an MCP server (persisted + applied live: connects if enabled). */
export async function upsertMcpServer(
  token: string,
  name: string,
  input: McpServerInput,
): Promise<McpServer> {
  const res = await fetch(`${API_BASE}/api/v1/mcp/servers/${encodeURIComponent(name)}`, {
    method: "PUT",
    credentials: CREDS,
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(`save MCP server failed: ${res.status}`);
  const body = (await res.json()) as { data?: { server?: McpServer } };
  return body.data!.server!;
}

// Per-tenant preference settings (#289). Every field is optional: null means "inherit the
// deployment default". Field names mirror the backend CoreConfig so the overlay is a plain copy.
export interface TenantSettings {
  model_provider: "ollama" | "openai_compat" | null;
  default_model: string | null;
  ollama_host: string | null;
  ollama_num_ctx: number | null;
  ollama_keep_alive: string | null;
  embed_provider: "ollama" | "openai_compat" | null;
  embed_model: string | null;
  openai_base_url: string | null;
  agent_mode: "single" | "multi" | "custom" | null;
  agent_graph_enabled: boolean | null;
  agent_human_gate: boolean | null;
  agent_accuracy_mode: "standard" | "accurate" | null;
  agent_max_iterations: number | null;
  agent_timeout_seconds: number | null;
  memory_enabled: boolean | null;
  grounding_enabled: boolean | null;
  max_upload_bytes: number | null;
  egress_enabled: boolean | null;
  allowed_egress_hosts: string[] | null;
  transcribe_enabled: boolean | null;
  transcribe_provider: "local" | "openai_compat" | null;
  transcribe_base_url: string | null;
  transcribe_model: string | null;
  transcribe_language: string | null;
  tts_enabled: boolean | null;
}

// The defaults the backend would apply for any field left null (echoed from the boot CoreConfig),
// so the UI can show the effective value as a placeholder.
export type TenantSettingsDefaults = {
  [K in keyof TenantSettings]: NonNullable<TenantSettings[K]>;
};

/** The request tenant's saved overrides plus the deployment defaults for the unset fields. */
export async function fetchSettings(
  token: string,
): Promise<{ settings: TenantSettings; defaults: TenantSettingsDefaults }> {
  const res = await fetch(`${API_BASE}/api/v1/settings`, {
    headers: authHeaders(token),
    credentials: CREDS,
  });
  if (!res.ok) throw new Error(`fetch settings failed: ${res.status}`);
  const body = (await res.json()) as {
    data?: { settings: TenantSettings; defaults: TenantSettingsDefaults };
  };
  return body.data!;
}

/** Replace the tenant's overrides (full overwrite; null/omitted fields restore the default). */
export async function saveSettings(
  token: string,
  settings: TenantSettings,
): Promise<TenantSettings> {
  const res = await fetch(`${API_BASE}/api/v1/settings`, {
    method: "PUT",
    credentials: CREDS,
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(settings),
  });
  if (!res.ok) throw new Error(`save settings failed: ${res.status}`);
  const body = (await res.json()) as { data?: { settings: TenantSettings } };
  return body.data!.settings;
}

/** Allow one egress host (interactive allow-on-deny): adds it to the allowlist + enables egress. */
export async function allowEgressHost(token: string, host: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/settings/egress/allow`, {
    method: "POST",
    credentials: CREDS,
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ host }),
  });
  if (!res.ok) throw new Error(`allow host failed: ${res.status}`);
}

/** The blocked host from an egress-denied tool error, or null if it isn't an egress denial. */
export function blockedEgressHost(error: string | null | undefined): string | null {
  if (!error || !/egress/i.test(error)) return null;
  const m =
    error.match(/host '([^']+)'/) ?? // "host 'X' is not in the egress allowlist"
    error.match(/attempted host: ([^);\s]+)/) ?? // "egress is disabled (attempted host: X)"
    error.match(/for host: (\S+)/); // "egress not allowed for host: X" (http_fetch)
  return m ? m[1].trim().replace(/[.,;]+$/, "") : null;
}

// Per-tenant multi-agent graph config (#290). One entry per agent the tenant has customized; a null
// prompt inherits the default, disabled_tools lists the tools that agent must not use.
export interface AgentConfigEntry {
  name: string;
  prompt: string | null;
  disabled_tools: string[];
}

export interface AgentGraphConfig {
  agents: AgentConfigEntry[];
}

export interface AgentRosterEntry {
  name: string;
  uses_tools: boolean;
}

/** The saved overrides plus the server-side roster, default prompts, and available tool names. */
export interface AgentConfigView {
  config: AgentGraphConfig;
  defaults: Record<string, string>;
  agents: AgentRosterEntry[];
  available_tools: string[];
}

/** The tenant's multi-agent graph config: saved overrides + defaults + roster + available tools. */
export async function fetchAgentConfig(token: string): Promise<AgentConfigView> {
  const res = await fetch(`${API_BASE}/api/v1/agents/config`, {
    headers: authHeaders(token),
    credentials: CREDS,
  });
  if (!res.ok) throw new Error(`fetch agent config failed: ${res.status}`);
  return ((await res.json()) as { data?: AgentConfigView }).data!;
}

/** Replace the tenant's agent overrides (full overwrite). */
export async function saveAgentConfig(
  token: string,
  config: AgentGraphConfig,
): Promise<AgentGraphConfig> {
  const res = await fetch(`${API_BASE}/api/v1/agents/config`, {
    method: "PUT",
    credentials: CREDS,
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(config),
  });
  if (!res.ok) throw new Error(`save agent config failed: ${res.status}`);
  return ((await res.json()) as { data?: { config: AgentGraphConfig } }).data!.config;
}

/** Bulk import a standard `mcpServers` map (merge + connect each live). Returns the updated list. */
export async function importMcpServers(
  token: string,
  mcpServers: Record<string, McpServerInput>,
): Promise<McpServer[]> {
  const res = await fetch(`${API_BASE}/api/v1/mcp/import`, {
    method: "POST",
    credentials: CREDS,
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ mcpServers }),
  });
  if (!res.ok) throw new Error(`import MCP servers failed: ${res.status}`);
  const body = (await res.json()) as { data?: { servers?: McpServer[] } };
  return body.data?.servers ?? [];
}

/** The whole mcpServers config (env masked) for the JSON editor / export. */
export async function fetchMcpConfig(token: string): Promise<McpConfig> {
  const res = await fetch(`${API_BASE}/api/v1/mcp/config`, { headers: authHeaders(token), credentials: CREDS });
  if (!res.ok) throw new Error(`mcp config request failed: ${res.status}`);
  const body = (await res.json()) as { data?: { mcpServers?: McpConfig } };
  return body.data?.mcpServers ?? {};
}

/** Replace the whole config and reconcile live. Returns the updated server list. */
export async function putMcpConfig(token: string, mcpServers: McpConfig): Promise<McpServer[]> {
  const res = await fetch(`${API_BASE}/api/v1/mcp/config`, {
    method: "PUT",
    credentials: CREDS,
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ mcpServers }),
  });
  if (!res.ok) throw new Error(`apply MCP config failed: ${res.status}`);
  const body = (await res.json()) as { data?: { servers?: McpServer[] } };
  return body.data?.servers ?? [];
}

/** Probe one server's health (Test). */
export async function checkMcpHealth(token: string, name: string): Promise<McpHealth> {
  const res = await fetch(
    `${API_BASE}/api/v1/mcp/servers/${encodeURIComponent(name)}/health`,
    { method: "POST", headers: authHeaders(token), credentials: CREDS },
  );
  if (!res.ok) throw new Error(`health check failed: ${res.status}`);
  const body = (await res.json()) as { data?: { health?: McpHealth } };
  return body.data!.health!;
}

/** MCP tool activity (namespaced server.tool calls) from the audit log, optionally one server. */
export async function fetchMcpLog(token: string, server?: string): Promise<ToolLogEntry[]> {
  const q = server ? `?server=${encodeURIComponent(server)}` : "";
  const res = await fetch(`${API_BASE}/api/v1/mcp/log${q}`, { headers: authHeaders(token), credentials: CREDS });
  if (!res.ok) throw new Error(`mcp log request failed: ${res.status}`);
  const body = (await res.json()) as { data?: { entries?: ToolLogEntry[] } };
  return body.data?.entries ?? [];
}

/** Disconnect (if connected) and remove an MCP server from the config. */
export async function deleteMcpServer(token: string, name: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/mcp/servers/${encodeURIComponent(name)}`, {
    method: "DELETE",
    headers: authHeaders(token),
    credentials: CREDS,
  });
  if (!res.ok) throw new Error(`delete MCP server failed: ${res.status}`);
}

/** The tool-call audit log (most recent first), optionally scoped to a conversation. */
export async function fetchToolLog(
  token: string,
  conversationId?: string | null,
): Promise<ToolLogEntry[]> {
  const res = await fetch(`${API_BASE}/api/v1/tools/log${convQuery(conversationId)}`, {
    headers: authHeaders(token),
    credentials: CREDS,
  });
  if (!res.ok) throw new Error(`tool log request failed: ${res.status}`);
  const body = (await res.json()) as { data?: { entries?: ToolLogEntry[] } };
  return body.data?.entries ?? [];
}

/** Invoke a tool through the gateway. */
export async function invokeTool(
  token: string,
  req: {
    tool: string;
    version: string;
    args: Record<string, unknown>;
    grants?: ToolPermission[];
    approved?: boolean;
  },
): Promise<ToolInvokeResult> {
  const res = await fetch(`${API_BASE}/api/v1/tools/invoke`, {
    method: "POST",
    credentials: CREDS,
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({
      tool: req.tool,
      version: req.version,
      args: req.args,
      grants: req.grants ?? [],
      approved: req.approved ?? false,
    }),
  });
  if (res.status === 400) throw new Error("invalid request");
  const body = (await res.json()) as {
    ok?: boolean;
    data?: Record<string, unknown>;
    error?: { message?: string };
  };
  return { ok: body.ok ?? false, data: body.data, error: body.error?.message };
}

/** List conversations (most-recent first). */
export async function fetchConversations(token: string): Promise<ConversationSummary[]> {
  const res = await fetch(`${API_BASE}/api/v1/conversations`, { headers: authHeaders(token), credentials: CREDS });
  if (!res.ok) throw new Error(`conversations request failed: ${res.status}`);
  const body = (await res.json()) as { data?: { conversations?: ConversationSummary[] } };
  return body.data?.conversations ?? [];
}

/** Load a conversation's messages. */
export async function fetchConversation(
  token: string,
  id: string,
): Promise<{ id: string; title: string; messages: ChatMessage[] }> {
  const res = await fetch(`${API_BASE}/api/v1/conversations/${id}`, { headers: authHeaders(token), credentials: CREDS });
  if (!res.ok) throw new Error(`conversation request failed: ${res.status}`);
  const body = (await res.json()) as {
    // The backend surfaces sent-message display data snake-cased (#426); normalize to the camelCase
    // `displayContent` the UI type uses (`documents`/`audio` are already single words). Old turns
    // have `display_content: null` -> stays undefined so the bubble falls back to `content`.
    data?: {
      id: string;
      title: string;
      messages: (ChatMessage & { display_content?: string | null })[];
    };
  };
  if (!body.data) throw new Error("conversation request failed");
  const messages: ChatMessage[] = body.data.messages.map((m) => {
    const { display_content, ...rest } = m;
    return display_content != null ? { ...rest, displayContent: display_content } : rest;
  });
  return { id: body.data.id, title: body.data.title, messages };
}

/** Delete a conversation. */
/** Rename a conversation. */
export async function renameConversation(token: string, id: string, title: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/conversations/${id}`, {
    method: "PATCH",
    credentials: CREDS,
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`rename conversation failed: ${res.status}`);
}

export async function deleteConversation(token: string, id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/conversations/${id}`, {
    method: "DELETE",
    headers: authHeaders(token),
    credentials: CREDS,
  });
  if (!res.ok) throw new Error(`delete conversation failed: ${res.status}`);
}

/** Truncate-from-turn (#441): delete the message with `fromMessageId` and EVERYTHING after it, in
 * one tenant-safe transaction. Backs Delete (truncate-only) and the first step of Edit (truncate,
 * then re-run via `streamChat`). `fromMessageId` is the stable `ChatMessage.id` from
 * `fetchConversation`, not an array index. Returns how many messages were deleted. */
export async function truncateConversation(
  token: string,
  conversationId: string,
  fromMessageId: number,
): Promise<{ deletedCount: number }> {
  const res = await fetch(`${API_BASE}/api/v1/conversations/${conversationId}/truncate`, {
    method: "POST",
    credentials: CREDS,
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ from_message_id: fromMessageId }),
  });
  if (!res.ok) throw new Error(`truncate failed: ${res.status}`);
  const body = (await res.json()) as { data?: { deleted_count?: number } };
  return { deletedCount: body.data?.deleted_count ?? 0 };
}

/**
 * Stream a chat completion. Calls `onDelta` for each token, `onCitations` for the RAG citations
 * event (if any), and resolves when done. Parses the SSE frames emitted by POST /api/v1/chat.
 */
export async function streamChat(
  params: {
    messages: ChatMessage[];
    model?: string;
    provider?: string;
    useRag?: boolean;
    useMemory?: boolean;
    useTools?: boolean;
    approveTools?: boolean;
    think?: boolean;
    reasoning?: "off" | "brief" | "full";
    conversationId?: string;
    token: string;
    // User-driven Stop (#412): aborting this signal closes the SSE fetch; the backend's generator
    // unwinds and persists the partial with meta["stopped"]. Mirrors describeImage/transcribeAudio.
    signal?: AbortSignal;
  },
  onDelta: (delta: string) => void,
  onCitations?: (citations: Citation[]) => void,
  onToolStep?: (step: ToolStep) => void,
  onUsage?: (usage: UsageInfo) => void,
  onThinking?: (delta: string, ts?: string) => void,
  onError?: (message: string) => void,
  onApproval?: (req: ApprovalRequest) => void,
  onAgentStep?: (step: { kind: "plan" | "critique"; text: string; ts?: string }) => void,
  onContext?: (context: ContextBreakdown) => void,
  onVerification?: (step: { text: string; verdict?: string; ts?: string }) => void,
  onDraft?: (step: { text: string; attempt?: number; ts?: string }) => void,
  // RAG-pipeline prelude steps (#437): indexing/retrieval/ner items the backend replays as trace
  // frames before the agent loop. The item IS a TraceItem; the caller appends it into the per-turn
  // trace so it streams in first (ahead of the agent steps) and matches the persisted meta["trace"].
  onPrelude?: (item: TraceItem) => void,
  // User-driven Stop (#412, path B): the backend emits a terminal `event: stopped` when a gated run
  // is cancelled mid-stream, so the UI can settle the "Generation stopped." marker deterministically
  // (vs only inferring it from a socket close). Not emitted on a pure client-disconnect (the client
  // already knows it aborted).
  onStopped?: () => void,
): Promise<void> {
  // Snake-case the sent-message display field (#426) for the backend's ChatMessageIn. `documents`/
  // `audio` are already single words; only `displayContent` -> `display_content` needs mapping.
  const wireMessages = params.messages.map((m) => {
    if (m.displayContent == null) return m;
    const { displayContent, ...rest } = m;
    return { ...rest, display_content: displayContent };
  });
  const res = await fetch(`${API_BASE}/api/v1/chat`, {
    method: "POST",
    credentials: CREDS,
    headers: { "Content-Type": "application/json", ...authHeaders(params.token) },
    body: JSON.stringify({
      messages: wireMessages,
      model: params.model,
      provider: params.provider,
      use_rag: params.useRag ?? false,
      use_memory: params.useMemory ?? false,
      use_tools: params.useTools ?? false,
      approve_tools: params.approveTools ?? false,
      think: params.think ?? false,
      reasoning: params.reasoning,
      conversation_id: params.conversationId,
    }),
    signal: params.signal,
  });
  if (!res.ok || res.body === null) throw new Error(`chat request failed: ${res.status}`);

  const processFrame = (frame: string): void => {
    const lines = frame.split("\n");
    const event = lines.find((l) => l.startsWith("event: "))?.slice("event: ".length);
    const dataLine = lines.find((l) => l.startsWith("data: "));
    if (dataLine === undefined) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(dataLine.slice("data: ".length));
    } catch {
      return; // skip a malformed/partial frame rather than aborting the whole stream
    }
    if (event === "context") return onContext?.(parsed as ContextBreakdown);
    if (event === "citations") return onCitations?.(parsed as Citation[]);
    if (event === "indexing" || event === "retrieval" || event === "ner" || event === "stage") {
      // The whole prelude item rides the frame; route it verbatim into the per-turn trace (#437).
      // `stage` (#465) is a transient live heartbeat handled by the same trace path (replaced in
      // place by appendTrace, cleared when the turn settles).
      return onPrelude?.(parsed as TraceItem);
    }
    if (event === "tool") return onToolStep?.(parsed as ToolStep);
    if (event === "plan" || event === "critique") {
      const p = parsed as { text?: string; ts?: string };
      return onAgentStep?.({ kind: event, text: p.text ?? "", ts: p.ts });
    }
    if (event === "verification") {
      const v = parsed as { text?: string; verdict?: string; ts?: string };
      return onVerification?.({ text: v.text ?? "", verdict: v.verdict, ts: v.ts });
    }
    if (event === "draft") {
      const d = parsed as { text?: string; attempt?: number; ts?: string };
      return onDraft?.({ text: d.text ?? "", attempt: d.attempt, ts: d.ts });
    }
    if (event === "usage") return onUsage?.(parsed as UsageInfo);
    if (event === "approval_request") return onApproval?.(parsed as ApprovalRequest);
    if (event === "stopped") return onStopped?.();
    if (event === "error") {
      onError?.((parsed as { error?: { message?: string } }).error?.message ?? "generation failed");
      return;
    }
    const payload = parsed as { delta?: string; thinking?: string | null; ts?: string };
    if (payload.thinking) onThinking?.(payload.thinking, payload.ts);
    if (payload.delta) onDelta(payload.delta);
  };

  await pumpSSE(res.body, processFrame);
}

/**
 * Resume a run suspended at the durable human gate (M8.1c). POSTs the human's decision and streams
 * the finalized continuation (the backend re-delivers the full answer as one delta + done).
 */
export async function resumeChat(
  params: {
    runId: string;
    decision: ResumeDecision | string;
    conversationId?: string;
    // The model provider the chat ran on. The egress gate re-runs the model on resume, so it needs
    // the provider; the answer gate can omit it (back-compat). Sent only when present.
    provider?: string;
    token: string;
  },
  onDelta: (delta: string) => void,
  onUsage?: (usage: UsageInfo) => void,
  onError?: (message: string) => void,
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/api/v1/chat/${encodeURIComponent(params.runId)}/resume`,
    {
      method: "POST",
      credentials: CREDS,
      headers: { "Content-Type": "application/json", ...authHeaders(params.token) },
      body: JSON.stringify({
        decision: params.decision,
        conversation_id: params.conversationId,
        ...(params.provider ? { provider: params.provider } : {}),
      }),
    },
  );
  if (!res.ok || res.body === null) throw new Error(`resume failed: ${res.status}`);

  const processFrame = (frame: string): void => {
    const lines = frame.split("\n");
    const event = lines.find((l) => l.startsWith("event: "))?.slice("event: ".length);
    const dataLine = lines.find((l) => l.startsWith("data: "));
    if (dataLine === undefined) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(dataLine.slice("data: ".length));
    } catch {
      return;
    }
    if (event === "usage") return onUsage?.(parsed as UsageInfo);
    if (event === "error") {
      onError?.((parsed as { error?: { message?: string } }).error?.message ?? "resume failed");
      return;
    }
    const payload = parsed as { delta?: string };
    if (payload.delta) onDelta(payload.delta);
  };

  await pumpSSE(res.body, processFrame);
}

/** Cancel a gated/suspended run (#412, path B): authoritative stop for a run that has a `run_id`
 * (suspended at a gate, or a gated streaming turn). Deletes the durable checkpoint so the run isn't
 * left resumable. Idempotent server-side (a finished run 404s; safe to ignore). Fired ADDITIONALLY
 * to aborting the SSE fetch — the abort (path A) covers non-gated turns, this cleans the checkpoint. */
export async function cancelChat(token: string, runId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/chat/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
    headers: authHeaders(token),
    credentials: CREDS,
  });
  // A finished/already-cancelled run 404s — that is fine (the run is already gone). Surface only
  // unexpected failures so a caller can log them; never throw on the idempotent 404.
  if (!res.ok && res.status !== 404) throw new Error(`cancel failed: ${res.status}`);
}

// --- Settings > Documents v2: folder sources (#458) ----------------------------------------------
// A watched on-disk folder whose files are scanned, chunked, and embedded into the tenant's global
// RAG index. The backend owns the scan lifecycle; the UI lists sources, registers/removes them, and
// drives Pause/Resume/Re-sync, streaming live scan progress over SSE.

export type FolderStatus = "idle" | "scanning" | "error" | "disabled";

// Per-file lifecycle bucket counts. Every bucket is optional: an absent bucket means zero, so the
// rollup line renders only the non-zero buckets (e.g. "312 synced · 4 indexing · 1 error").
export interface FolderCounts {
  pending?: number;
  indexing?: number;
  synced?: number;
  stale?: number;
  error?: number;
  deleted?: number;
}

export interface FolderSource {
  id: string;
  root_path: string;
  label: string;
  enabled: boolean;
  status: FolderStatus;
  status_detail: string | null;
  counts: FolderCounts;
  last_scan_finished_at: string | null;
  created_at: string;
}

// A structured backend error ({code, message}); surfaced inline by the add form / card so the user
// sees the specific reason (E_FOLDER_NOT_FOUND / E_FOLDER_NOT_A_DIR / E_FOLDER_EXISTS / ...).
export interface FolderError {
  code: string;
  message: string;
}

// Per-file lifecycle status (the drill-down, #458 pass 2). Same vocabulary as the bucket counts.
export type FolderFileStatus =
  | "pending"
  | "indexing"
  | "synced"
  | "stale"
  | "error"
  | "deleted";

// One watched file under a folder source. `rel_path` is a POSIX path that CAN be nested
// (e.g. "reports/2024/q3.pdf") — the detail UI derives a directory tree from these. The backend does
// NOT store per-stage pipeline meta (no model/ms), so the UI shows only these honest facts.
export interface FolderFileOut {
  rel_path: string;
  status: FolderFileStatus;
  document_id: string | null; // the global document id when indexed (links to the doc), else null
  size_bytes: number | null;
  error_code: string | null;
  error_detail: string | null;
  indexed_at: string | null; // ISO timestamp of the last successful index, else null
}

// A page of a folder source's detail: the source itself plus a keyset page of its files (paginated on
// `rel_path`, lexicographic — so a directory's files are contiguous). `total` is the full file count
// when the backend reports it (so the UI can show "X of Y loaded"), else null.
export interface FolderDetail {
  source: FolderSource;
  files: FolderFileOut[];
  total: number | null;
}

// register / resync return a discriminated result rather than throwing, so the caller can render the
// specific structured error (bad path, already-registered, paused) inline instead of a generic toast.
export type RegisterFolderResult =
  | { ok: true; folder: FolderSource }
  | { ok: false; error: FolderError };

export type ResyncResult = { ok: true } | { ok: false; error: FolderError };

// Read a `{ok,data|error}` envelope, tolerating non-2xx (the backend returns the structured error as
// the body). Returns the parsed envelope, or a synthesized transport error when the body is unusable.
async function readFolderEnvelope(
  res: Response,
): Promise<{ ok?: boolean; data?: unknown; error?: FolderError }> {
  try {
    return (await res.json()) as { ok?: boolean; data?: unknown; error?: FolderError };
  } catch {
    return { ok: false, error: { code: "E_TRANSPORT", message: `request failed: ${res.status}` } };
  }
}

/** List the tenant's registered folder sources. */
export async function fetchFolders(token: string): Promise<FolderSource[]> {
  const res = await fetch(`${API_BASE}/api/v1/folders`, {
    headers: authHeaders(token),
    credentials: CREDS,
  });
  if (!res.ok) throw new Error(`folders request failed: ${res.status}`);
  const body = (await res.json()) as { data?: { folders?: FolderSource[] } };
  return body.data?.folders ?? [];
}

/** Fetch one folder source's detail + a keyset page of its files (#458 pass 2). `after` is the last
 * `rel_path` from the previous page (keyset cursor); `status` narrows server-side; `limit` <= 200.
 * `total` is read best-effort from whichever count field the backend supplies (else null). */
export async function fetchFolderDetail(
  token: string,
  id: string,
  opts: { status?: FolderFileStatus; after?: string; limit?: number } = {},
): Promise<FolderDetail> {
  const url = new URL(`${API_BASE}/api/v1/folders/${encodeURIComponent(id)}`);
  if (opts.status) url.searchParams.set("status", opts.status);
  if (opts.after) url.searchParams.set("after", opts.after);
  if (opts.limit != null) url.searchParams.set("limit", String(Math.min(opts.limit, 200)));
  const res = await fetch(url, { headers: authHeaders(token), credentials: CREDS });
  if (!res.ok) throw new Error(`folder detail failed: ${res.status}`);
  const body = (await res.json()) as {
    data?: {
      source?: FolderSource;
      files?: FolderFileOut[];
      // The backend may report the full count under any of these keys; read defensively.
      total?: number;
      total_files?: number;
      file_count?: number;
    };
  };
  const data = body.data;
  if (!data?.source) throw new Error("folder detail failed");
  const total = data.total ?? data.total_files ?? data.file_count ?? null;
  return { source: data.source, files: data.files ?? [], total };
}

// --- Settings > Documents v2: entity browser / knowledge graph (#451 NER+KAG) --------------------
// Entities are corpus-GLOBAL (the same entity can span many documents/folders), extracted by NER as
// documents are indexed — so the browser is a top-level Documents section, not a per-folder view.

export type EntityType =
  | "person"
  | "org"
  | "location"
  | "date"
  | "product"
  | "event"
  | "other";

export interface Entity {
  id: string;
  type: EntityType;
  name: string;
  mention_count: number;
}

// One knowledge-graph edge from an entity to another (relation -> dst entity).
export interface EntityEdge {
  relation: string;
  dst_entity_id: string;
}

// An entity plus its provenance: the documents it was mentioned in and its outgoing graph edges.
export interface EntityDetail {
  entity: Entity;
  documents: string[]; // document_id[]
  edges: EntityEdge[];
}

/** List corpus-global entities (#451). `type` filters by kind; `q` is a fuzzy name search; `limit`
 * caps the result. All optional — omitted params list everything (up to the backend default). */
export async function fetchEntities(
  token: string,
  opts: { type?: EntityType; q?: string; limit?: number } = {},
): Promise<Entity[]> {
  const url = new URL(`${API_BASE}/api/v1/entities`);
  if (opts.type) url.searchParams.set("type", opts.type);
  if (opts.q) url.searchParams.set("q", opts.q);
  if (opts.limit != null) url.searchParams.set("limit", String(opts.limit));
  const res = await fetch(url, { headers: authHeaders(token), credentials: CREDS });
  if (!res.ok) throw new Error(`entities request failed: ${res.status}`);
  const body = (await res.json()) as { data?: { entities?: Entity[] } };
  return body.data?.entities ?? [];
}

/** Fetch one entity's detail (#451): the entity, its source documents, and its graph edges. */
export async function fetchEntityDetail(token: string, id: string): Promise<EntityDetail> {
  const res = await fetch(`${API_BASE}/api/v1/entities/${encodeURIComponent(id)}`, {
    headers: authHeaders(token),
    credentials: CREDS,
  });
  if (!res.ok) throw new Error(`entity detail failed: ${res.status}`);
  const body = (await res.json()) as {
    data?: { entity?: Entity; documents?: string[]; edges?: EntityEdge[] };
  };
  if (!body.data?.entity) throw new Error("entity detail failed");
  return {
    entity: body.data.entity,
    documents: body.data.documents ?? [],
    edges: body.data.edges ?? [],
  };
}

// One co-occurring entity in an ego-graph: the neighbor plus how many documents it shares with the
// focus (the edge weight). Entity-entity edges are sparse, so co-occurrence is the meaningful link.
export interface EntityNeighbor {
  entity: Entity;
  shared_documents: number;
}

// The focus+context ego-graph for one entity (#KAG): the focus entity, the documents it appears in
// (the bipartite doc nodes), and the entities it co-occurs with (weighted by shared documents). The
// backend caps the result; the UI renders the focus + docs + neighbors as a small node-link graph.
export interface EntityNeighborhood {
  focus: Entity;
  documents: { id: string; name: string }[];
  neighbors: EntityNeighbor[];
}

/** Fetch an entity's ego-graph (#KAG): its documents + co-occurring entities (weighted), capped
 * server-side at `cap` so the canvas never has to render an unbounded hairball. */
export async function fetchEntityNeighborhood(
  token: string,
  id: string,
  cap = 200,
): Promise<EntityNeighborhood> {
  const url = new URL(`${API_BASE}/api/v1/entities/${encodeURIComponent(id)}/neighborhood`);
  url.searchParams.set("cap", String(cap));
  const res = await fetch(url, { headers: authHeaders(token), credentials: CREDS });
  if (!res.ok) throw new Error(`neighborhood request failed: ${res.status}`);
  const body = (await res.json()) as {
    data?: {
      focus?: Entity;
      documents?: { id: string; name: string }[];
      neighbors?: EntityNeighbor[];
    };
  };
  if (!body.data?.focus) throw new Error("neighborhood request failed");
  return {
    focus: body.data.focus,
    documents: body.data.documents ?? [],
    neighbors: body.data.neighbors ?? [],
  };
}

/** The entities extracted from a single document (#KAG), for the corpus table's per-doc entity count
 * and the graph detail rail when a document node is selected. */
export async function fetchDocumentEntities(token: string, id: string): Promise<Entity[]> {
  const res = await fetch(`${API_BASE}/api/v1/documents/${encodeURIComponent(id)}/entities`, {
    headers: authHeaders(token),
    credentials: CREDS,
  });
  if (!res.ok) throw new Error(`document entities request failed: ${res.status}`);
  const body = (await res.json()) as { data?: { entities?: Entity[] } };
  return body.data?.entities ?? [];
}

// One indexed chunk of a document (#KAG chunk inspector): its 0-based position in the document and
// the chunk text the retriever embeds and searches over.
export interface DocumentChunk {
  index: number;
  text: string;
}

/** The chunks a single document was split into (#KAG), for the Corpus chunk inspector. Unwraps the
 * StructuredResult envelope like fetchEntityNeighborhood / fetchDocumentEntities. */
export async function fetchDocumentChunks(token: string, id: string): Promise<DocumentChunk[]> {
  const res = await fetch(`${API_BASE}/api/v1/documents/${encodeURIComponent(id)}/chunks`, {
    headers: authHeaders(token),
    credentials: CREDS,
  });
  if (!res.ok) throw new Error(`document chunks request failed: ${res.status}`);
  const body = (await res.json()) as { data?: { chunks?: DocumentChunk[] } };
  return body.data?.chunks ?? [];
}

// --- Settings > Knowledge: Retrieval Explorer (#465) ---------------------------------------------
// Standalone hybrid retrieval over the GLOBAL corpus (no chat answer): the Settings playground that
// shows what the retriever would surface for a query. Rank is the primary signal; the RRF-fused
// `score` is only meaningful relative to its siblings (shown as a relative bar, never an absolute).

/** One ranked passage from POST /api/v1/retrieve: its rank, text, fused score, and provenance
 * (source document name + locator + source kind). `locator`/`name` may be null (unnamed source). */
export interface RetrievedPassage {
  rank: number;
  text: string;
  score: number;
  source_id: string;
  locator: string | null;
  name: string | null;
  source_kind: string;
}

/** The standalone-retrieval result for the Knowledge Retrieval Explorer. `scope` is always
 * "global" today (the durable corpus); `ms` is the retrieval wall-clock. */
export interface RetrievalResult {
  query: string;
  scope: "global";
  top_k: number;
  ms: number | null;
  passages: RetrievedPassage[];
}

/** Run standalone hybrid retrieval over the global corpus (#465) — ranked passages with score +
 * provenance, NO chat answer. Backs the Settings > Knowledge Retrieval Explorer. Unwraps the
 * StructuredResult envelope like fetchEntityNeighborhood / fetchFiles. */
export async function retrievePassages(
  token: string,
  q: string,
  topK = 8,
): Promise<RetrievalResult> {
  const res = await fetch(`${API_BASE}/api/v1/retrieve`, {
    method: "POST",
    credentials: CREDS,
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ q, top_k: topK }),
  });
  if (!res.ok) throw new Error(`retrieve failed: ${res.status}`);
  const body = (await res.json()) as {
    ok?: boolean;
    error?: { message?: string };
    data?: {
      query?: string;
      scope?: "global";
      top_k?: number;
      ms?: number | null;
      passages?: RetrievedPassage[];
    };
  };
  if (body.ok === false) throw new Error(body.error?.message ?? "retrieve failed");
  return {
    query: body.data?.query ?? q,
    scope: body.data?.scope ?? "global",
    top_k: body.data?.top_k ?? topK,
    ms: body.data?.ms ?? null,
    passages: body.data?.passages ?? [],
  };
}

/** Register a folder source. Returns a discriminated result so the form can surface the structured
 * error ({code, message}) inline; never throws on a structured backend error (bad path / duplicate). */
export async function registerFolder(
  token: string,
  path: string,
  label?: string,
): Promise<RegisterFolderResult> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/folders`, {
      method: "POST",
      credentials: CREDS,
      headers: { "Content-Type": "application/json", ...authHeaders(token) },
      body: JSON.stringify({ path, ...(label ? { label } : {}) }),
    });
  } catch {
    return { ok: false, error: { code: "E_NETWORK", message: "Could not reach the backend." } };
  }
  const body = await readFolderEnvelope(res);
  if (body.ok === true && body.data) return { ok: true, folder: body.data as FolderSource };
  return {
    ok: false,
    error: body.error ?? { code: "E_UNKNOWN", message: `register failed: ${res.status}` },
  };
}

/** Remove a folder source. Returns how many indexed documents were purged. */
export async function deleteFolder(token: string, id: string): Promise<{ purgedDocuments: number }> {
  const res = await fetch(`${API_BASE}/api/v1/folders/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: authHeaders(token),
    credentials: CREDS,
  });
  if (!res.ok) throw new Error(`delete folder failed: ${res.status}`);
  const body = (await res.json()) as { data?: { purged_documents?: number } };
  return { purgedDocuments: body.data?.purged_documents ?? 0 };
}

/** Trigger a re-scan. Returns a discriminated result so a paused source (E_FOLDER_PAUSED) surfaces
 * inline rather than throwing. */
export async function resyncFolder(token: string, id: string): Promise<ResyncResult> {
  const res = await fetch(`${API_BASE}/api/v1/folders/${encodeURIComponent(id)}/resync`, {
    method: "POST",
    headers: authHeaders(token),
    credentials: CREDS,
  });
  const body = await readFolderEnvelope(res);
  if (body.ok === true) return { ok: true };
  return {
    ok: false,
    error: body.error ?? { code: "E_UNKNOWN", message: `re-sync failed: ${res.status}` },
  };
}

/** Pause watching/scanning a source. Returns the updated source. */
export async function pauseFolder(token: string, id: string): Promise<FolderSource> {
  const res = await fetch(`${API_BASE}/api/v1/folders/${encodeURIComponent(id)}/pause`, {
    method: "POST",
    headers: authHeaders(token),
    credentials: CREDS,
  });
  if (!res.ok) throw new Error(`pause folder failed: ${res.status}`);
  const body = (await res.json()) as { data?: FolderSource };
  if (!body.data) throw new Error("pause folder failed");
  return body.data;
}

/** Resume watching/scanning a paused source. Returns the updated source. */
export async function resumeFolder(token: string, id: string): Promise<FolderSource> {
  const res = await fetch(`${API_BASE}/api/v1/folders/${encodeURIComponent(id)}/resume`, {
    method: "POST",
    headers: authHeaders(token),
    credentials: CREDS,
  });
  if (!res.ok) throw new Error(`resume folder failed: ${res.status}`);
  const body = (await res.json()) as { data?: FolderSource };
  if (!body.data) throw new Error("resume folder failed");
  return body.data;
}

// One live scan-progress tick from the SSE stream. `done` is true on the terminal `event: done`
// frame, after which the stream closes server-side.
export interface FolderProgressEvent {
  id: string;
  status: FolderStatus;
  counts: FolderCounts;
  done: boolean;
}

/** Stream a folder source's live scan progress (#458). Calls `onProgress` for each `progress` frame
 * and once more for the terminal `done` frame (with `done: true`). Best-effort: a transport error or
 * an aborted `signal` (the caller unmounting) resolves quietly so the card keeps its last-known
 * counts rather than surfacing a spurious error. Uses fetch + `pumpSSE`, like `streamChat`. */
export async function streamFolderEvents(
  id: string,
  onProgress: (event: FolderProgressEvent) => void,
  token: string,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/folders/${encodeURIComponent(id)}/events`, {
      headers: authHeaders(token),
      credentials: CREDS,
      signal,
    });
  } catch {
    return; // abort or transport error — keep last-known counts, no spurious error
  }
  if (!res.ok || res.body === null) return;

  const processFrame = (frame: string): void => {
    const lines = frame.split("\n");
    const event = lines.find((l) => l.startsWith("event: "))?.slice("event: ".length);
    const dataLine = lines.find((l) => l.startsWith("data: "));
    if (dataLine === undefined) return;
    if (event !== "progress" && event !== "done") return;
    let parsed: { id?: string; status?: FolderStatus; counts?: FolderCounts };
    try {
      parsed = JSON.parse(dataLine.slice("data: ".length));
    } catch {
      return; // skip a malformed/partial frame rather than aborting the stream
    }
    onProgress({
      id: parsed.id ?? id,
      status: parsed.status ?? "scanning",
      counts: parsed.counts ?? {},
      done: event === "done",
    });
  };

  try {
    await pumpSSE(res.body, processFrame);
  } catch {
    // Reader aborted (unmount) or stream torn down — best-effort, nothing to surface.
  }
}

/** Read an SSE body to completion, dispatching each `\n\n`-delimited frame (incl. a trailing one). */
async function pumpSSE(body: ReadableStream<Uint8Array>, onFrame: (frame: string) => void): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) if (frame.trim()) onFrame(frame);
  }
  // Flush any multi-byte remainder + a trailing frame that lacked the final "\n\n" (otherwise the
  // last event — sometimes the answer or the error notice — is dropped).
  buffer += decoder.decode();
  if (buffer.trim()) onFrame(buffer);
}
