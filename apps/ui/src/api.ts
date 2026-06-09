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

export interface TraceItem {
  kind: "reasoning" | "tool_call" | "tool_result";
  text?: string;
  tool?: string | null;
  args?: Record<string, unknown> | null;
  ok?: boolean | null;
  output?: Record<string, unknown> | null;
  error?: string | null;
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

function authHeaders(token: string): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
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
  const res = await fetch(`${API_BASE}/api/v1/providers`, { headers: authHeaders(token) });
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
  const res = await fetch(url, { headers: authHeaders(token) });
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
  const res = await fetch(`${API_BASE}/api/v1/files`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(`files request failed: ${res.status}`);
  const body = (await res.json()) as { data?: { files?: DocumentInfo[] } };
  return body.data?.files ?? [];
}

/** Delete an ingested document. */
export async function deleteFile(token: string, id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/files/${id}`, {
    method: "DELETE",
    headers: authHeaders(token),
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
  const res = await fetch(`${API_BASE}/api/v1/memory`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(`memory request failed: ${res.status}`);
  const body = (await res.json()) as { data?: { memories?: MemoryItem[] } };
  return body.data?.memories ?? [];
}

/** Edit a memory's text. */
export async function updateMemory(token: string, id: string, text: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/memory/${id}`, {
    method: "PATCH",
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
  });
  if (!res.ok) throw new Error(`delete memory failed: ${res.status}`);
}

/** Forget everything (delete all memories). */
export async function forgetAllMemory(token: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/memory`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(`forget all failed: ${res.status}`);
}

/** List the tools registered behind the gateway. */
export async function fetchTools(token: string): Promise<ToolInfo[]> {
  const res = await fetch(`${API_BASE}/api/v1/tools`, { headers: authHeaders(token) });
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
  });
  if (!res.ok) throw new Error(`logs request failed: ${res.status}`);
  const body = (await res.json()) as { data?: { logs?: LogEntry[] } };
  return body.data?.logs ?? [];
}

/** Configured MCP servers + connect status + the tools each exposed. */
export async function fetchMcp(token: string): Promise<McpServer[]> {
  const res = await fetch(`${API_BASE}/api/v1/mcp`, { headers: authHeaders(token) });
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
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(`save MCP server failed: ${res.status}`);
  const body = (await res.json()) as { data?: { server?: McpServer } };
  return body.data!.server!;
}

/** Disconnect (if connected) and remove an MCP server from the config. */
export async function deleteMcpServer(token: string, name: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/mcp/servers/${encodeURIComponent(name)}`, {
    method: "DELETE",
    headers: authHeaders(token),
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
  const res = await fetch(`${API_BASE}/api/v1/conversations`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(`conversations request failed: ${res.status}`);
  const body = (await res.json()) as { data?: { conversations?: ConversationSummary[] } };
  return body.data?.conversations ?? [];
}

/** Load a conversation's messages. */
export async function fetchConversation(
  token: string,
  id: string,
): Promise<{ id: string; title: string; messages: ChatMessage[] }> {
  const res = await fetch(`${API_BASE}/api/v1/conversations/${id}`, { headers: authHeaders(token) });
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
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`rename conversation failed: ${res.status}`);
}

export async function deleteConversation(token: string, id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/conversations/${id}`, {
    method: "DELETE",
    headers: authHeaders(token),
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
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/chat`, {
    method: "POST",
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

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const lines = frame.split("\n");
      const event = lines.find((l) => l.startsWith("event: "))?.slice("event: ".length);
      const dataLine = lines.find((l) => l.startsWith("data: "));
      if (dataLine === undefined) continue;
      const data = dataLine.slice("data: ".length);
      if (event === "citations") {
        onCitations?.(JSON.parse(data) as Citation[]);
        continue;
      }
      if (event === "tool") {
        onToolStep?.(JSON.parse(data) as ToolStep);
        continue;
      }
      if (event === "usage") {
        onUsage?.(JSON.parse(data) as UsageInfo);
        continue;
      }
      if (event === "error") {
        const e = JSON.parse(data) as { error?: { message?: string } };
        onError?.(e.error?.message ?? "generation failed");
        continue;
      }
      const payload = JSON.parse(data) as { delta?: string; thinking?: string | null };
      if (payload.thinking) onThinking?.(payload.thinking);
      if (payload.delta) onDelta(payload.delta);
    }
  }
}
