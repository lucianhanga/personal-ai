import { useEffect, useRef, useState } from "react";

import {
  createConversation,
  deleteConversation,
  deleteFile,
  fetchConversation,
  fetchConversations,
  fetchFiles,
  fetchMemories,
  fetchModels,
  fetchProviders,
  streamChat,
  uploadFile,
  type ChatMessage,
  type Citation,
  type ConversationSummary,
  type DocumentInfo,
  type ModelInfo,
  type ToolStep,
  type UsageInfo,
} from "./api";
import { AppLogs } from "./AppLogs";
import { ContextMeter } from "./ContextMeter";
import { Markdown } from "./Markdown";
import { Memory } from "./Memory";
import { ToolLog } from "./ToolLog";
import { Tools } from "./Tools";

export function Chat({
  token,
  status = "connected",
  statusLabel = "",
  onToken,
}: {
  token: string;
  status?: string;
  statusLabel?: string;
  onToken?: (value: string) => void;
}): React.ReactElement {
  const [providers, setProviders] = useState<string[]>([]);
  const [provider, setProvider] = useState<string>("");
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [model, setModel] = useState<string>("");
  const [files, setFiles] = useState<DocumentInfo[]>([]);
  const [useRag, setUseRag] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [useMemory, setUseMemory] = useState(true);
  const [useTools, setUseTools] = useState(true);
  const [approveTools, setApproveTools] = useState(true);
  const [incognito, setIncognito] = useState(false);
  const [showSettings, setShowSettings] = useState(true);
  const [showMemory, setShowMemory] = useState(false);
  const [showTools, setShowTools] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [showAppLogs, setShowAppLogs] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [chatsCollapsed, setChatsCollapsed] = useState(false);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [persistence, setPersistence] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [citations, setCitations] = useState<Record<number, Citation[]>>({});
  const [toolSteps, setToolSteps] = useState<Record<number, ToolStep[]>>({});
  const [usage, setUsage] = useState<UsageInfo | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    fetchProviders(token)
      .then(({ default: def, providers }) => {
        if (!active) return;
        setProviders(providers);
        setProvider(def || providers[0] || "");
      })
      .catch((e: unknown) => active && setError(String(e)));
    return () => {
      active = false;
    };
  }, [token]);

  useEffect(() => {
    if (!provider) return;
    let active = true;
    setError(null);
    fetchModels(token, provider)
      .then(({ defaultModel, models }) => {
        if (!active) return;
        setModels(models);
        setModel(models.some((m) => m.name === defaultModel) ? defaultModel : models[0]?.name || "");
      })
      .catch((e: unknown) => active && setError(String(e)));
    return () => {
      active = false;
    };
  }, [token, provider]);

  useEffect(() => {
    let active = true;
    // Files require storage; if unavailable the list just stays empty (no hard error).
    fetchFiles(token)
      .then((f) => {
        if (!active) return;
        setFiles(f);
        // If documents are already present, default to using them (avoids silently
        // ungrounded answers after a reload).
        if (f.length > 0) setUseRag(true);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [token]);

  useEffect(() => {
    let active = true;
    // Default "use my memory" on when there is anything remembered (mirrors the RAG default).
    fetchMemories(token)
      .then((m) => active && m.length > 0 && setUseMemory(true))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [token]);

  useEffect(() => {
    let active = true;
    // Conversation history requires storage; if unavailable, persistence stays off.
    fetchConversations(token)
      .then((c) => {
        if (!active) return;
        setConversations(c);
        setPersistence(true);
      })
      .catch(() => active && setPersistence(false));
    return () => {
      active = false;
    };
  }, [token]);

  useEffect(() => {
    listRef.current?.scrollTo(0, listRef.current.scrollHeight);
  }, [messages]);

  function newChat(): void {
    setConversationId(null);
    setMessages([]);
    setCitations({});
    setError(null);
  }

  async function openConversation(id: string): Promise<void> {
    setError(null);
    try {
      const conv = await fetchConversation(token, id);
      setConversationId(conv.id);
      setMessages(conv.messages);
      setCitations({});
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  async function removeConversation(id: string): Promise<void> {
    try {
      await deleteConversation(token, id);
      setConversations(conversations.filter((c) => c.id !== id));
      if (id === conversationId) newChat();
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  async function onUpload(file: File | undefined): Promise<void> {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      await uploadFile(token, file);
      setFiles(await fetchFiles(token));
      setUseRag(true);
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setUploading(false);
    }
  }

  async function onDelete(id: string): Promise<void> {
    try {
      await deleteFile(token, id);
      setFiles(files.filter((f) => f.id !== id));
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  async function send(): Promise<void> {
    const content = input.trim();
    if (!content || busy) return;
    setError(null);
    setInput("");
    const history: ChatMessage[] = [...messages, { role: "user", content }];
    const assistantIndex = history.length;
    setMessages([...history, { role: "assistant", content: "" }]);
    setBusy(true);
    try {
      // Persist into a conversation (create one lazily on the first message).
      let convId = conversationId;
      if (persistence && convId === null) {
        const conv = await createConversation(token, content.slice(0, 60), incognito);
        convId = conv.id;
        setConversationId(conv.id);
      }
      let acc = "";
      await streamChat(
        {
          messages: history,
          model,
          provider,
          useRag,
          useMemory,
          useTools,
          approveTools,
          conversationId: convId ?? undefined,
          token,
        },
        (delta) => {
          acc += delta;
          setMessages([...history, { role: "assistant", content: acc }]);
        },
        (cites) => setCitations((prev) => ({ ...prev, [assistantIndex]: cites })),
        (step) =>
          setToolSteps((prev) => ({
            ...prev,
            [assistantIndex]: [...(prev[assistantIndex] ?? []), step],
          })),
        (u) => setUsage(u),
      );
      if (persistence) setConversations(await fetchConversations(token));
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const selected = models.find((m) => m.name === model);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", height: "100%" }}>
      {/* Row 1: top bar (non-collapsable) — identity, status, token, provider/model. */}
      <header
        data-testid="top-bar"
        style={{
          display: "flex",
          gap: "0.75rem",
          alignItems: "center",
          flexWrap: "wrap",
          borderBottom: "1px solid #ddd",
          paddingBottom: "0.5rem",
        }}
      >
        <h1 style={{ margin: 0, fontSize: "1.3rem" }}>Personal AI</h1>
        <span
          data-testid="backend-status"
          data-status={status}
          style={{ fontSize: "0.85rem", color: "#555" }}
        >
          {statusLabel}
        </span>
        <span data-testid="provider-badge" style={{ fontSize: "0.85rem", color: "#555" }}>
          Local
        </span>
        <label style={{ fontSize: "0.85rem" }}>
          Token:{" "}
          <input
            data-testid="token-input"
            type="password"
            value={token}
            placeholder="PERSONALAI_AUTH_TOKEN"
            onChange={(e) => onToken?.(e.target.value)}
          />
        </label>
        <label htmlFor="provider" style={{ marginLeft: "auto" }}>
          Provider:
        </label>
        <select
          id="provider"
          data-testid="provider-select"
          value={provider}
          onChange={(e) => setProvider(e.target.value)}
        >
          {providers.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <label htmlFor="model">Model:</label>
        <select
          id="model"
          data-testid="model-select"
          value={model}
          onChange={(e) => setModel(e.target.value)}
        >
          {models.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name}
            </option>
          ))}
        </select>
        {selected && (
          <span data-testid="model-caps" style={{ fontSize: "0.8rem", color: "#555" }}>
            {[
              selected.local ? "local" : "remote",
              selected.capabilities.vision && "vision",
              selected.capabilities.tool_calling && "tools",
              selected.capabilities.thinking && "thinking",
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
        )}
      </header>

      {/* Row 2: global settings (collapsible accordion). */}
      <div
        data-testid="settings-accordion"
        style={{ border: "1px solid #ddd", borderRadius: 8, fontSize: "0.85rem" }}
      >
        <button
          data-testid="settings-toggle"
          onClick={() => setShowSettings((v) => !v)}
          style={{
            width: "100%",
            textAlign: "left",
            background: "none",
            border: "none",
            cursor: "pointer",
            padding: "0.5rem 0.75rem",
            fontWeight: 600,
          }}
        >
          {showSettings ? "▾" : "▸"} Settings
        </button>
        {showSettings && (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "0.5rem",
              padding: "0 0.75rem 0.75rem",
            }}
          >
            {/* Line 1: Documents */}
            <div
              data-testid="settings-documents"
              style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}
            >
              <label>
                Documents:{" "}
                <input
                  data-testid="file-input"
                  type="file"
                  accept=".txt,.md,.markdown,.pdf,.docx"
                  disabled={uploading}
                  onChange={(e) => void onUpload(e.target.files?.[0])}
                />
              </label>
              {uploading && <span data-testid="upload-status">uploading…</span>}
              {files.length > 0 && !useRag && (
                <span data-testid="rag-hint" style={{ marginLeft: "auto", color: "#b06f00" }}>
                  Not using your documents — turn on to ground answers.
                </span>
              )}
              <label style={{ marginLeft: files.length > 0 && !useRag ? "0.5rem" : "auto" }}>
                <input
                  data-testid="rag-toggle"
                  type="checkbox"
                  checked={useRag}
                  onChange={(e) => setUseRag(e.target.checked)}
                />{" "}
                Use my documents
              </label>
            </div>

            {/* Line 2: Tools */}
            <div
              data-testid="settings-tools"
              style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}
            >
              <button data-testid="tools-show" onClick={() => setShowTools((v) => !v)}>
                {showTools ? "Hide tools" : "Tools"}
              </button>
              <label style={{ marginLeft: "auto" }}>
                <input
                  data-testid="tools-toggle"
                  type="checkbox"
                  checked={useTools}
                  onChange={(e) => setUseTools(e.target.checked)}
                />{" "}
                Use tools
              </label>
              {useTools && (
                <label title="Allow high-risk tools (e.g. http_fetch) to run this session">
                  <input
                    data-testid="approve-tools-toggle"
                    type="checkbox"
                    checked={approveTools}
                    onChange={(e) => setApproveTools(e.target.checked)}
                  />{" "}
                  approve high-risk
                </label>
              )}
            </div>
            {showTools && <Tools token={token} />}

            {/* Line 3: Memory */}
            <div
              data-testid="settings-memory"
              style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}
            >
              <button data-testid="memory-show" onClick={() => setShowMemory((v) => !v)}>
                {showMemory ? "Hide memory" : "Memory"}
              </button>
              <label style={{ marginLeft: "auto" }}>
                <input
                  data-testid="memory-toggle"
                  type="checkbox"
                  checked={useMemory}
                  onChange={(e) => setUseMemory(e.target.checked)}
                />{" "}
                Use my memory
              </label>
            </div>
            {showMemory && <Memory token={token} />}
          </div>
        )}
      </div>

      {/* Row 3: workspace — chats (1/6) | chat (3/6) | logs (2/6). */}
      {token ? (
        <div
          data-testid="workspace"
          style={{
            display: "flex",
            gap: "1rem",
            alignItems: "stretch",
            width: "100%",
            flex: 1,
            minHeight: 0,
          }}
        >
          {/* Column 1: chats (collapsible) */}
          {!chatsCollapsed ? (
            <aside
              data-testid="chats-panel"
              style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: "0.4rem" }}
            >
              <div style={{ display: "flex", alignItems: "center" }}>
                <strong style={{ flex: 1 }}>Chats</strong>
                <button
                  data-testid="chats-toggle"
                  onClick={() => setChatsCollapsed(true)}
                  title="Collapse chats"
                >
                  ‹
                </button>
              </div>
              <button data-testid="new-chat" onClick={() => newChat()}>
                + New chat
              </button>
              <label style={{ fontSize: "0.8rem" }} title="Incognito chats are not remembered">
                <input
                  data-testid="incognito-toggle"
                  type="checkbox"
                  checked={incognito}
                  onChange={(e) => setIncognito(e.target.checked)}
                />{" "}
                incognito
              </label>
              <div
                data-testid="conversations"
                style={{ display: "flex", flexDirection: "column", gap: "0.2rem", overflowY: "auto" }}
              >
                {conversations.map((c) => (
                  <span
                    key={c.id}
                    style={{ display: "flex", alignItems: "center", gap: "0.25rem", fontSize: "0.8rem" }}
                  >
                    <button
                      data-testid={`open-${c.id}`}
                      onClick={() => void openConversation(c.id)}
                      style={{
                        flex: 1,
                        textAlign: "left",
                        fontWeight: c.id === conversationId ? 700 : 400,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {c.title}
                    </button>
                    <button
                      data-testid={`del-conv-${c.id}`}
                      onClick={() => void removeConversation(c.id)}
                      title="delete conversation"
                      style={{ fontSize: "0.7rem" }}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            </aside>
          ) : (
            <button
              data-testid="chats-toggle"
              onClick={() => setChatsCollapsed(false)}
              title="Show chats"
              style={{ flex: "0 0 auto", alignSelf: "flex-start" }}
            >
              Chats ›
            </button>
          )}

          {/* Column 2: chat output + composer */}
          <section
            aria-label="chat"
            data-testid="chat-col"
            style={{ flex: 3, minWidth: 0, display: "flex", flexDirection: "column", gap: "0.5rem" }}
          >
            {files.length > 0 && (
              <ul
                data-testid="file-list"
                style={{ margin: 0, paddingLeft: "1rem", fontSize: "0.8rem" }}
              >
                {files.map((f) => (
                  <li key={f.id} data-testid="file-item">
                    {f.name} <span style={{ color: "#888" }}>({f.chunk_count} chunks)</span>{" "}
                    <button
                      data-testid={`delete-${f.id}`}
                      onClick={() => void onDelete(f.id)}
                      style={{ fontSize: "0.75rem" }}
                    >
                      remove
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <div
              ref={listRef}
              data-testid="messages"
              style={{
                border: "1px solid #ddd",
                borderRadius: 8,
                padding: "0.75rem",
                flex: 1,
                minHeight: 200,
                overflowY: "auto",
              }}
            >
              {messages.length === 0 && (
                <p style={{ color: "#888" }}>Ask your local model anything.</p>
              )}
              {messages.map((m, i) =>
                m.role === "assistant" ? (
                  <div key={i} data-testid="msg-assistant" style={{ margin: "0.4rem 0" }}>
                    <strong>AI:</strong>
                    {toolSteps[i]?.length ? (
                      <div data-testid="tool-steps" style={{ fontSize: "0.75rem", color: "#555" }}>
                        {toolSteps[i].map((s, k) =>
                          s.phase === "call" ? (
                            <div key={k}>
                              🔧 {s.tool}({JSON.stringify(s.args ?? {})})
                            </div>
                          ) : (
                            <div key={k} style={{ color: s.ok ? "#2a7" : "#b00" }}>
                              ↳ {s.tool}: {s.ok ? "ok" : `error: ${s.error}`}
                            </div>
                          ),
                        )}
                      </div>
                    ) : null}
                    <Markdown content={m.content} />
                    {citations[i]?.length ? (
                      <div data-testid="citations" style={{ fontSize: "0.75rem", color: "#555" }}>
                        Sources:{" "}
                        {citations[i]
                          .map(
                            (c) =>
                              `[${c.n}] ${c.name ?? c.source_id.slice(0, 8)}` +
                              (c.locator ? ` (${c.locator})` : ""),
                          )
                          .join("   ")}
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <p key={i} data-testid="msg-user" style={{ margin: "0.4rem 0" }}>
                    <strong>You:</strong> {m.content}
                  </p>
                ),
              )}
            </div>

            {error && (
              <p data-testid="chat-error" style={{ color: "#b00" }}>
                {error}
              </p>
            )}

            <div style={{ display: "flex", gap: "0.5rem" }}>
              <input
                data-testid="composer"
                style={{ flex: 1 }}
                value={input}
                placeholder="Type a message..."
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void send();
                }}
              />
              <button data-testid="send" onClick={() => void send()} disabled={busy || !model}>
                {busy ? "..." : "Send"}
              </button>
            </div>
          </section>

          {/* Column 3: logs (collapsible) */}
          {!sidebarCollapsed ? (
            <aside
              data-testid="side-panel"
              aria-label="panels"
              style={{ flex: 2, minWidth: 0, display: "flex", flexDirection: "column", gap: "0.5rem" }}
            >
              <div style={{ display: "flex", gap: "0.4rem", alignItems: "center", flexWrap: "wrap" }}>
                <button data-testid="toollog-show" onClick={() => setShowLog((v) => !v)}>
                  {showLog ? "Hide log" : "Log"}
                </button>
                <button data-testid="applogs-show" onClick={() => setShowAppLogs((v) => !v)}>
                  {showAppLogs ? "Hide app logs" : "App logs"}
                </button>
                <button
                  data-testid="side-toggle"
                  onClick={() => setSidebarCollapsed(true)}
                  title="Collapse panel"
                  style={{ marginLeft: "auto" }}
                >
                  Collapse ›
                </button>
              </div>

              {usage && <ContextMeter usage={usage} />}

              {showLog && <ToolLog token={token} conversationId={conversationId} />}
              {showAppLogs && <AppLogs token={token} conversationId={conversationId} />}

              {!showLog && !showAppLogs && !usage && (
                <p data-testid="side-hint" style={{ color: "#888", fontSize: "0.8rem" }}>
                  Open a panel above to view logs or context usage.
                </p>
              )}
            </aside>
          ) : (
            <button
              data-testid="side-toggle"
              onClick={() => setSidebarCollapsed(false)}
              title="Show panels"
              style={{ flex: "0 0 auto", alignSelf: "flex-start" }}
            >
              ‹ Panels
            </button>
          )}
        </div>
      ) : (
        <p data-testid="need-token" style={{ color: "#888" }}>
          Enter your backend API token to start chatting.
        </p>
      )}

      <p data-testid="security-note" style={{ color: "#555", fontSize: "0.8rem" }}>
        Local-first: network egress is disabled by default; remote providers are opt-in.
      </p>
    </div>
  );
}
