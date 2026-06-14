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
  renameConversation,
  resumeChat,
  streamChat,
  uploadFile,
  type ApprovalRequest,
  type ChatMessage,
  type Citation,
  type ConversationSummary,
  type DocumentInfo,
  type ModelInfo,
  type TraceItem,
  type UsageInfo,
} from "./api";
import { ChatsPanel } from "./ChatsPanel";
import { MessageList } from "./MessageList";
import { SettingsAccordion } from "./SettingsAccordion";
import { SidePanel } from "./SidePanel";

// Key for the not-yet-persisted "new" chat (before its conversation id exists).
const NEW_CHAT = "__new__";

/** All per-conversation state, so chats stream independently and survive switching. */
interface ChatState {
  messages: ChatMessage[];
  citations: Record<number, Citation[]>;
  // Ordered reasoning + tool-step timeline per assistant message index.
  trace: Record<number, TraceItem[]>;
  usage: UsageInfo | null;
  busy: boolean;
  // Set when a turn is suspended at the durable human gate (M8.1c), awaiting approve/reject.
  pending: ApprovalRequest | null;
}

const EMPTY_CHAT: ChatState = {
  messages: [],
  citations: {},
  trace: {},
  usage: null,
  busy: false,
  pending: null,
};

/** Append a trace item in order, merging consecutive reasoning deltas into one item. */
function appendTrace(list: TraceItem[] | undefined, item: TraceItem): TraceItem[] {
  const next = [...(list ?? [])];
  const last = next[next.length - 1];
  if (item.kind === "reasoning" && last?.kind === "reasoning") {
    next[next.length - 1] = { ...last, text: (last.text ?? "") + (item.text ?? "") };
  } else {
    next.push(item);
  }
  return next;
}

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
  // Default to "brief": reasoning on but bounded, so large reasoning models (e.g. 35B) don't
  // over-deliberate and appear to hang. "Off"/"Full" remain selectable.
  const [reasoning, setReasoning] = useState<"off" | "brief" | "full">("brief");
  const [incognito, setIncognito] = useState(false);
  const [showSettings, setShowSettings] = useState(true);
  const [showMemory, setShowMemory] = useState(false);
  const [showTools, setShowTools] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [showAppLogs, setShowAppLogs] = useState(false);
  const [showMcp, setShowMcp] = useState(false);
  const [showMcpActivity, setShowMcpActivity] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [chatsCollapsed, setChatsCollapsed] = useState(false);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  // Per-conversation state, keyed by conversation id (NEW_CHAT for the unsaved one). Streams run
  // independently against their key, so switching chats never interrupts a generating answer.
  const [chats, setChats] = useState<Record<string, ChatState>>({});
  const [persistence, setPersistence] = useState(false);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  const activeKey = activeId ?? NEW_CHAT;
  const view = chats[activeKey] ?? EMPTY_CHAT;
  const { messages, citations, trace, usage, busy, pending } = view;

  const patchChat = (key: string, fn: (s: ChatState) => ChatState): void => {
    setChats((prev) => ({ ...prev, [key]: fn(prev[key] ?? EMPTY_CHAT) }));
  };

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

  // Sticky-bottom auto-scroll: follow new content while the user is at the bottom; if they scroll
  // up, pause until they return to the bottom (then resume). `atBottom` also drives a jump button.
  const stickToBottom = useRef(true);
  const [atBottom, setAtBottom] = useState(true);

  function onMessagesScroll(): void {
    const el = listRef.current;
    if (!el) return;
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    stickToBottom.current = bottom;
    setAtBottom(bottom);
  }

  function scrollToBottom(): void {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    stickToBottom.current = true;
    setAtBottom(true);
  }

  useEffect(() => {
    if (stickToBottom.current && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, trace]);

  function newChat(): void {
    setChats((prev) => ({ ...prev, [NEW_CHAT]: EMPTY_CHAT }));
    setActiveId(null);
    setError(null);
  }

  async function openConversation(id: string): Promise<void> {
    setError(null);
    setActiveId(id);
    // If this chat is mid-stream, keep its live state; otherwise load from the server.
    if (chats[id]?.busy) return;
    try {
      const conv = await fetchConversation(token, id);
      // If the chat started streaming while we were loading, keep its live state (don't clobber).
      setChats((prev) =>
        prev[id]?.busy
          ? prev
          : { ...prev, [id]: { ...EMPTY_CHAT, messages: conv.messages, usage: prev[id]?.usage ?? null } },
      );
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  async function commitRename(id: string): Promise<void> {
    const title = renameDraft.trim();
    setRenamingId(null);
    if (!title) return;
    try {
      await renameConversation(token, id, title);
      setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, title } : c)));
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  async function removeConversation(id: string): Promise<void> {
    try {
      await deleteConversation(token, id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      setChats((prev) => {
        const { [id]: _omit, ...rest } = prev;
        return rest;
      });
      if (id === activeId) newChat();
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
    if (!content || !model || view.busy) return;
    setError(null);
    setInput("");

    const startKey = activeId ?? NEW_CHAT;
    const history: ChatMessage[] = [...(chats[startKey]?.messages ?? []), { role: "user", content }];
    const assistantIndex = history.length;
    // Optimistically show the user turn + an empty assistant bubble and mark this chat busy.
    patchChat(startKey, (s) => ({
      ...s,
      messages: [...history, { role: "assistant", content: "" }],
      busy: true,
      usage: null,
    }));

    let targetId = activeId;
    let key = startKey;
    try {
      // Persist into a conversation (create lazily on the first message); migrate the optimistic
      // state from NEW_CHAT to the real id so streaming continues there.
      if (persistence && targetId === null) {
        const conv = await createConversation(token, content.slice(0, 60), incognito);
        targetId = conv.id;
        key = conv.id;
        setChats((prev) => {
          const cur = prev[NEW_CHAT] ?? EMPTY_CHAT;
          const { [NEW_CHAT]: _omit, ...rest } = prev;
          return { ...rest, [conv.id]: cur };
        });
        setActiveId((cur) => (cur === null ? conv.id : cur)); // don't yank focus if user switched
        setConversations(await fetchConversations(token)); // show the new chat (with its marker)
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
          think: reasoning !== "off",
          reasoning,
          conversationId: targetId ?? undefined,
          token,
        },
        (delta) => {
          acc += delta;
          patchChat(key, (s) => ({ ...s, messages: [...history, { role: "assistant", content: acc }] }));
        },
        (cites) => patchChat(key, (s) => ({ ...s, citations: { ...s.citations, [assistantIndex]: cites } })),
        (step) =>
          patchChat(key, (s) => ({
            ...s,
            trace: {
              ...s.trace,
              [assistantIndex]: appendTrace(s.trace[assistantIndex], {
                kind: step.phase === "call" ? "tool_call" : "tool_result",
                tool: step.tool,
                args: step.args,
                ok: step.ok,
                output: step.output,
                error: step.error,
              }),
            },
          })),
        (u) => patchChat(key, (s) => ({ ...s, usage: u })),
        (delta) =>
          patchChat(key, (s) => ({
            ...s,
            trace: {
              ...s.trace,
              [assistantIndex]: appendTrace(s.trace[assistantIndex], {
                kind: "reasoning",
                text: delta,
              }),
            },
          })),
        (message) => {
          // Surface backend errors in the assistant bubble instead of silently ending the turn.
          acc = (acc ? acc + "\n\n" : "") + `**Error:** ${message}`;
          patchChat(key, (s) => ({
            ...s,
            messages: [...history, { role: "assistant", content: acc }],
          }));
        },
        (req) => {
          // Durable human gate (M8.1c): the turn is suspended; the proposed answer is already in the
          // bubble (acc). Stash the run so Approve/Reject can resume it.
          patchChat(key, (s) => ({ ...s, pending: req }));
        },
        (step) =>
          // M8 multi-agent flow: stream planner/critic steps into the live trace so the user can
          // follow which agent did what, in order with the researcher's tool/reasoning steps.
          patchChat(key, (s) => ({
            ...s,
            trace: {
              ...s.trace,
              [assistantIndex]: appendTrace(s.trace[assistantIndex], {
                kind: step.kind,
                text: step.text,
              }),
            },
          })),
      );
      if (persistence) setConversations(await fetchConversations(token));
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      patchChat(key, (s) => ({ ...s, busy: false }));
    }
  }

  // Resolve a turn suspended at the durable human gate (M8.1c): resume with the decision, stream the
  // finalized answer into the same assistant bubble, and clear the pending state.
  async function resolveApproval(decision: "approve" | "reject"): Promise<void> {
    const key = activeKey;
    const cur = chats[key];
    if (!cur?.pending) return;
    const runId = cur.pending.run_id;
    const idx = cur.messages.length - 1; // the suspended assistant message
    setError(null);
    patchChat(key, (s) => ({ ...s, busy: true, pending: null }));
    try {
      await resumeChat(
        { runId, decision, conversationId: activeId ?? undefined, token },
        (delta) => {
          // Resume re-delivers the full answer as one delta -> set the bubble content.
          patchChat(key, (s) => {
            const msgs = [...s.messages];
            msgs[idx] = { role: "assistant", content: delta };
            return { ...s, messages: msgs };
          });
        },
        (u) => patchChat(key, (s) => ({ ...s, usage: u })),
        (message) => setError(message),
      );
      if (persistence) setConversations(await fetchConversations(token));
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      patchChat(key, (s) => ({ ...s, busy: false }));
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
      <SettingsAccordion
        token={token}
        showSettings={showSettings}
        setShowSettings={setShowSettings}
        files={files}
        uploading={uploading}
        onUpload={(f) => void onUpload(f)}
        useRag={useRag}
        setUseRag={setUseRag}
        showTools={showTools}
        setShowTools={setShowTools}
        useTools={useTools}
        setUseTools={setUseTools}
        approveTools={approveTools}
        setApproveTools={setApproveTools}
        showMemory={showMemory}
        setShowMemory={setShowMemory}
        useMemory={useMemory}
        setUseMemory={setUseMemory}
        reasoning={reasoning}
        setReasoning={setReasoning}
        showMcp={showMcp}
        setShowMcp={setShowMcp}
      />

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
          <ChatsPanel
            collapsed={chatsCollapsed}
            setCollapsed={setChatsCollapsed}
            conversations={conversations}
            chats={chats}
            activeId={activeId}
            incognito={incognito}
            setIncognito={setIncognito}
            renamingId={renamingId}
            setRenamingId={setRenamingId}
            renameDraft={renameDraft}
            setRenameDraft={setRenameDraft}
            onNewChat={newChat}
            onOpen={(id) => void openConversation(id)}
            onCommitRename={(id) => void commitRename(id)}
            onRemove={(id) => void removeConversation(id)}
          />

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

            <MessageList
              messages={messages}
              trace={trace}
              citations={citations}
              busy={busy}
              listRef={listRef}
              onScroll={onMessagesScroll}
            />

            {!atBottom && (
              <button
                data-testid="scroll-bottom"
                onClick={scrollToBottom}
                style={{ alignSelf: "center", fontSize: "0.75rem", marginTop: "-0.25rem" }}
              >
                ↓ Jump to latest
              </button>
            )}

            {pending && (
              <div
                data-testid="approval-request"
                style={{
                  border: "1px solid #c90",
                  background: "#fff8e1",
                  borderRadius: "0.4rem",
                  padding: "0.5rem 0.75rem",
                  fontSize: "0.85rem",
                }}
              >
                <strong>Approval needed</strong> — review the proposed answer above before it is
                finalized.
                {pending.critique ? (
                  <p style={{ margin: "0.35rem 0", color: "#555" }}>Critique: {pending.critique}</p>
                ) : null}
                <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.35rem" }}>
                  <button
                    data-testid="approve"
                    onClick={() => void resolveApproval("approve")}
                    disabled={busy}
                  >
                    Approve
                  </button>
                  <button
                    data-testid="reject"
                    onClick={() => void resolveApproval("reject")}
                    disabled={busy}
                  >
                    Reject
                  </button>
                </div>
              </div>
            )}

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
          <SidePanel
            token={token}
            conversationId={activeId}
            usage={usage}
            collapsed={sidebarCollapsed}
            setCollapsed={setSidebarCollapsed}
            showLog={showLog}
            setShowLog={setShowLog}
            showAppLogs={showAppLogs}
            setShowAppLogs={setShowAppLogs}
            showMcpActivity={showMcpActivity}
            setShowMcpActivity={setShowMcpActivity}
          />
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
