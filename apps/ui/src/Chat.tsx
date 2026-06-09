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
} from "./api";
import { Markdown } from "./Markdown";
import { Memory } from "./Memory";
import { ToolLog } from "./ToolLog";
import { Tools } from "./Tools";

export function Chat({ token }: { token: string }): React.ReactElement {
  const [providers, setProviders] = useState<string[]>([]);
  const [provider, setProvider] = useState<string>("");
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [model, setModel] = useState<string>("");
  const [files, setFiles] = useState<DocumentInfo[]>([]);
  const [useRag, setUseRag] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [useMemory, setUseMemory] = useState(false);
  const [useTools, setUseTools] = useState(false);
  const [approveTools, setApproveTools] = useState(false);
  const [incognito, setIncognito] = useState(false);
  const [showMemory, setShowMemory] = useState(false);
  const [showTools, setShowTools] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [persistence, setPersistence] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [citations, setCitations] = useState<Record<number, Citation[]>>({});
  const [toolSteps, setToolSteps] = useState<Record<number, ToolStep[]>>({});
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
    <section aria-label="chat" style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
      {persistence && (
        <div
          data-testid="conversations"
          style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}
        >
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
          {conversations.map((c) => (
            <span key={c.id} style={{ fontSize: "0.8rem" }}>
              <button
                data-testid={`open-${c.id}`}
                onClick={() => void openConversation(c.id)}
                style={{
                  fontWeight: c.id === conversationId ? 700 : 400,
                  maxWidth: 160,
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
      )}
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <label htmlFor="provider">Provider:</label>
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
      </div>

      <div
        data-testid="documents"
        style={{
          display: "flex",
          gap: "0.5rem",
          alignItems: "center",
          flexWrap: "wrap",
          fontSize: "0.85rem",
        }}
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
        <label>
          <input
            data-testid="memory-toggle"
            type="checkbox"
            checked={useMemory}
            onChange={(e) => setUseMemory(e.target.checked)}
          />{" "}
          Use my memory
        </label>
        <label>
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
        <button data-testid="memory-show" onClick={() => setShowMemory((v) => !v)}>
          {showMemory ? "Hide memory" : "Memory"}
        </button>
        <button data-testid="tools-show" onClick={() => setShowTools((v) => !v)}>
          {showTools ? "Hide tools" : "Tools"}
        </button>
        <button data-testid="toollog-show" onClick={() => setShowLog((v) => !v)}>
          {showLog ? "Hide log" : "Log"}
        </button>
      </div>

      {showMemory && <Memory token={token} />}
      {showTools && <Tools token={token} />}
      {showLog && <ToolLog token={token} />}

      {files.length > 0 && (
        <ul data-testid="file-list" style={{ margin: 0, paddingLeft: "1rem", fontSize: "0.8rem" }}>
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
          height: 320,
          overflowY: "auto",
        }}
      >
        {messages.length === 0 && <p style={{ color: "#888" }}>Ask your local model anything.</p>}
        {messages.map((m, i) =>
          m.role === "assistant" ? (
            // Assistant replies render as Markdown (block elements, so not inside a <p>).
            <div key={i} data-testid="msg-assistant" style={{ margin: "0.4rem 0" }}>
              <strong>AI:</strong>
              {toolSteps[i]?.length ? (
                <div data-testid="tool-steps" style={{ fontSize: "0.75rem", color: "#555" }}>
                  {toolSteps[i].map((s, k) =>
                    s.phase === "call" ? (
                      <div key={k}>🔧 {s.tool}({JSON.stringify(s.args ?? {})})</div>
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
            // User input stays literal text.
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
  );
}
