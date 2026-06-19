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
  kind: "reasoning" | "tool_call" | "tool_result" | "plan" | "critique" | "verification";
  text?: string;
  role?: string | null; // which agent produced it (researcher/critic/verifier) — M8
  verdict?: string | null; // verification outcome (e.g. "pass"/"fail"/"needs-revision") — M8
  tool?: string | null;
  args?: Record<string, unknown> | null;
  ok?: boolean | null;
  output?: Record<string, unknown> | null;
  error?: string | null;
}

/** A durable human-gate approval request (M8.1c): the run is suspended until POST .../resume. */
export interface ApprovalRequest {
  run_id: string;
  reason?: string;
  answer?: string;
  critique?: string;
}

export interface MessageMeta {
  // Ordered timeline of reasoning + tool steps (new format).
  trace?: TraceItem[];
  // Legacy (pre-ordered-trace) fields, kept for older persisted messages.
  tool_steps?: ToolStep[];
  thinking?: string;
}

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
  // Persisted per-assistant-message detail (tool calls + reasoning), shown collapsed in the UI.
  meta?: MessageMeta | null;
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
}

// What was assembled into the model's context this turn (grounding, documents, memory, ...), so the
// user can see the composition and approximate size as the question is asked.
export interface ContextItem {
  label: string;
  count: number;
  chars: number;
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

/** List ingested documents. */
export async function fetchFiles(token: string): Promise<DocumentInfo[]> {
  const res = await fetch(`${API_BASE}/api/v1/files`, { headers: authHeaders(token), credentials: CREDS });
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
  memory_enabled: boolean | null;
  grounding_enabled: boolean | null;
  max_upload_bytes: number | null;
  egress_enabled: boolean | null;
  allowed_egress_hosts: string[] | null;
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
  const m = error.match(/host '([^']+)'/) ?? error.match(/attempted host: ([^);]+)/);
  return m ? m[1].trim() : null;
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
    data?: { id: string; title: string; messages: ChatMessage[] };
  };
  if (!body.data) throw new Error("conversation request failed");
  return body.data;
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
  },
  onDelta: (delta: string) => void,
  onCitations?: (citations: Citation[]) => void,
  onToolStep?: (step: ToolStep) => void,
  onUsage?: (usage: UsageInfo) => void,
  onThinking?: (delta: string) => void,
  onError?: (message: string) => void,
  onApproval?: (req: ApprovalRequest) => void,
  onAgentStep?: (step: { kind: "plan" | "critique"; text: string }) => void,
  onContext?: (context: ContextBreakdown) => void,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/chat`, {
    method: "POST",
    credentials: CREDS,
    headers: { "Content-Type": "application/json", ...authHeaders(params.token) },
    body: JSON.stringify({
      messages: params.messages,
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
    if (event === "tool") return onToolStep?.(parsed as ToolStep);
    if (event === "plan" || event === "critique") {
      return onAgentStep?.({ kind: event, text: (parsed as { text?: string }).text ?? "" });
    }
    if (event === "usage") return onUsage?.(parsed as UsageInfo);
    if (event === "approval_request") return onApproval?.(parsed as ApprovalRequest);
    if (event === "error") {
      onError?.((parsed as { error?: { message?: string } }).error?.message ?? "generation failed");
      return;
    }
    const payload = parsed as { delta?: string; thinking?: string | null };
    if (payload.thinking) onThinking?.(payload.thinking);
    if (payload.delta) onDelta(payload.delta);
  };

  await pumpSSE(res.body, processFrame);
}

/**
 * Resume a run suspended at the durable human gate (M8.1c). POSTs the human's decision and streams
 * the finalized continuation (the backend re-delivers the full answer as one delta + done).
 */
export async function resumeChat(
  params: { runId: string; decision: string; conversationId?: string; token: string },
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
      body: JSON.stringify({ decision: params.decision, conversation_id: params.conversationId }),
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
