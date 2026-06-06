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

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
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
  const res = await fetch(`${API_BASE}/api/providers`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(`providers request failed: ${res.status}`);
  const body = (await res.json()) as { data?: { default?: string; providers?: string[] } };
  return { default: body.data?.default ?? "", providers: body.data?.providers ?? [] };
}

/** List a provider's models (with capabilities) and the default model. */
export async function fetchModels(
  token: string,
  provider?: string,
): Promise<{ defaultModel: string; models: ModelInfo[] }> {
  const url = new URL(`${API_BASE}/api/models`);
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

/**
 * Stream a chat completion. Calls `onDelta` for each token and resolves when done.
 * Parses the SSE frames emitted by POST /api/chat.
 */
export async function streamChat(
  params: { messages: ChatMessage[]; model?: string; provider?: string; token: string },
  onDelta: (delta: string) => void,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(params.token) },
    body: JSON.stringify({
      messages: params.messages,
      model: params.model,
      provider: params.provider,
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
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (line === undefined) continue;
      const payload = JSON.parse(line.slice("data: ".length)) as { delta?: string };
      if (payload.delta) onDelta(payload.delta);
    }
  }
}
