import { useEffect, useRef, useState } from "react";

import {
  createConversation,
  deleteConversation,
  deleteFile,
  fetchConversation,
  fetchConversations,
  fetchFiles,
  fetchMemories,
  allowEgressHost,
  blockedEgressHost,
  fetchModels,
  fetchProviders,
  fetchSettings,
  renameConversation,
  resumeChat,
  saveSettings,
  streamChat,
  uploadFile,
  type ApprovalRequest,
  type ChatMessage,
  type Citation,
  type ContextBreakdown,
  type ConversationSummary,
  type DocumentInfo,
  type ModelInfo,
  type TenantSettings,
  type TraceItem,
  type UsageInfo,
} from "./api";
import { ChatsPanel } from "./ChatsPanel";
import { MessageList } from "./MessageList";
import { SettingsView } from "./SettingsView";
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
  // The context composition assembled for the latest turn (what went into the prompt).
  context: ContextBreakdown | null;
  busy: boolean;
  // Set when a turn is suspended at the durable human gate (M8.1c), awaiting approve/reject.
  pending: ApprovalRequest | null;
}

const EMPTY_CHAT: ChatState = {
  messages: [],
  citations: {},
  trace: {},
  usage: null,
  context: null,
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
  // The tenant's saved settings, loaded once. The top-bar model selector is the single source of
  // truth and writes the chosen model back here as the persisted default, so it survives reloads.
  const settingsRef = useRef<TenantSettings | null>(null);
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
  // Two-view navigation: the chat workspace vs the full-width Settings view (#290 redesign).
  const [tab, setTab] = useState<"chat" | "settings">("chat");
  // A host an outbound tool call was blocked on this turn, offered for one-click allow-on-deny.
  const [blockedHost, setBlockedHost] = useState<string | null>(null);
  const [allowedHost, setAllowedHost] = useState<string | null>(null);
  const [showLog, setShowLog] = useState(false);
  const [showAppLogs, setShowAppLogs] = useState(false);
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
  const { messages, citations, trace, usage, context, busy, pending } = view;

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

  // Load the saved settings once so the model selector can persist the chosen default. If storage
  // is unavailable (no DB), persistence is silently skipped and selection stays session-only.
  useEffect(() => {
    fetchSettings(token)
      .then(({ settings }) => {
        settingsRef.current = settings;
      })
      .catch(() => {
        settingsRef.current = null;
      });
  }, [token]);

  // Persist the chosen model as the tenant default (best-effort; the selection still applies this
  // session even if the write fails). Merges into the loaded settings so other fields are preserved.
  function persistDefaultModel(name: string): void {
    const base = settingsRef.current;
    if (base === null || name === "") return;
    const next: TenantSettings = { ...base, default_model: name };
    settingsRef.current = next;
    void saveSettings(token, next).catch(() => undefined);
  }

  function onModelChange(name: string): void {
    setModel(name);
    persistDefaultModel(name);
  }

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

  async function onAllowHost(host: string): Promise<void> {
    try {
      await allowEgressHost(token, host);
      setBlockedHost(null);
      setAllowedHost(host);
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  async function send(): Promise<void> {
    const content = input.trim();
    if (!content || !model || view.busy) return;
    setError(null);
    setBlockedHost(null);
    setAllowedHost(null);
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
        (step) => {
          // Offer one-click allow-on-deny when an outbound tool call was blocked by egress.
          if (step.phase === "result" && step.error) {
            const host = blockedEgressHost(step.error);
            if (host) setBlockedHost(host);
          }
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
          }));
        },
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
        // The context composition for this turn, shown in the side panel as the question is asked.
        (ctx) => patchChat(key, (s) => ({ ...s, context: ctx })),
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
        {/* Chat | Settings view switch (two-tab navigation). */}
        <div role="tablist" aria-label="view" style={{ display: "flex", gap: "0.25rem" }}>
          {(["chat", "settings"] as const).map((v) => (
            <button
              key={v}
              role="tab"
              aria-selected={tab === v}
              aria-current={tab === v ? "page" : undefined}
              data-testid={`nav-${v}`}
              onClick={() => setTab(v)}
              style={{
                padding: "0.25rem 0.6rem",
                background: "none",
                border: "none",
                cursor: "pointer",
                fontSize: "0.9rem",
                fontWeight: tab === v ? 600 : 400,
                borderBottom: tab === v ? "2px solid #1a7f37" : "2px solid transparent",
              }}
            >
              {v === "chat" ? "Chat" : "Settings"}
            </button>
          ))}
        </div>
        {/* Backend health as a color dot + label (green ok, red down, amber checking). */}
        <span
          data-testid="backend-status"
          data-status={status}
          title={statusLabel}
          style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem", fontSize: "0.85rem", color: "#555" }}
        >
          <span
            aria-hidden
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background:
                status === "connected" ? "#1a7f37" : status === "loading" ? "#b06f00" : "#b00",
            }}
          />
          {statusLabel}
        </span>
        {/* Model selection is a Chat-view concern (per-turn); hidden on the Settings view. */}
        {tab === "chat" && (
          <>
            <label htmlFor="model" style={{ marginLeft: "auto", fontSize: "0.85rem", color: "#555" }}>
              Model
            </label>
            <select
              id="model"
              data-testid="model-select"
              value={model}
              onChange={(e) => onModelChange(e.target.value)}
            >
              {models.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}
                </option>
              ))}
            </select>
            {/* The provider selector only appears when more than one is configured (local-first:
                usually just Ollama, so it stays out of the way). */}
            {providers.length > 1 && (
              <select
                data-testid="provider-select"
                aria-label="provider"
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
              >
                {providers.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            )}
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
          </>
        )}
      </header>

      {tab === "settings" ? (
        <SettingsView
          token={token}
          onToken={onToken}
          files={files}
          uploading={uploading}
          onUpload={(f) => void onUpload(f)}
          onDelete={(id) => void onDelete(id)}
        />
      ) : (
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

            {/* Interactive allow-on-deny: an outbound request was blocked; offer to allow the host. */}
            {blockedHost && (
              <div
                data-testid="egress-block-banner"
                style={{
                  border: "1px solid #b06f00",
                  color: "#b06f00",
                  borderRadius: 6,
                  padding: "0.5rem",
                  fontSize: "0.82rem",
                  display: "flex",
                  gap: "0.5rem",
                  alignItems: "center",
                  flexWrap: "wrap",
                }}
              >
                <span style={{ flex: 1 }}>
                  Outbound request to <strong>{blockedHost}</strong> was blocked by the egress
                  allowlist.
                </span>
                <button data-testid="egress-allow-btn" onClick={() => void onAllowHost(blockedHost)}>
                  Allow {blockedHost}
                </button>
              </div>
            )}
            {allowedHost && (
              <div data-testid="egress-allowed-banner" style={{ color: "#1a7f37", fontSize: "0.82rem" }}>
                Allowed <strong>{allowedHost}</strong> and added it to your allowlist — re-send your
                message to use it.
              </div>
            )}

            {/* Per-session controls strip: these are per-turn toggles, kept next to the composer. */}
            <div
              data-testid="session-controls"
              style={{
                display: "flex",
                gap: "0.75rem",
                alignItems: "center",
                flexWrap: "wrap",
                fontSize: "0.85rem",
                borderTop: "1px solid #eee",
                paddingTop: "0.4rem",
              }}
            >
              <label>
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
              <label>
                <input
                  data-testid="memory-toggle"
                  type="checkbox"
                  checked={useMemory}
                  onChange={(e) => setUseMemory(e.target.checked)}
                />{" "}
                Use my memory
              </label>
              <label
                style={{ marginLeft: "auto" }}
                title="How much the model thinks before answering. Off = none; Brief = concise; Full = think freely (slower)."
              >
                Reasoning{" "}
                <select
                  data-testid="reasoning-select"
                  value={reasoning}
                  onChange={(e) => setReasoning(e.target.value as "off" | "brief" | "full")}
                >
                  <option value="off">Off</option>
                  <option value="brief">Brief</option>
                  <option value="full">Full</option>
                </select>
              </label>
            </div>
            {files.length > 0 && !useRag && (
              <span data-testid="rag-hint" style={{ color: "#b06f00", fontSize: "0.8rem" }}>
                Not using your documents — turn on “Use my documents” to ground answers.
              </span>
            )}

            <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-end" }}>
              <textarea
                data-testid="composer"
                rows={4}
                style={{ flex: 1, resize: "vertical", font: "inherit", padding: "0.4rem" }}
                value={input}
                placeholder="Type a message...  (Enter to send, Shift+Enter for a new line)"
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  // Enter sends; Shift+Enter inserts a newline. Ignore Enter mid-IME composition
                  // (e.g. Japanese/Chinese input) so committing a candidate doesn't send.
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    void send();
                  }
                }}
              />
              <button
                data-testid="send"
                onClick={() => void send()}
                disabled={busy || !model || input.trim() === ""}
              >
                {busy ? "..." : "Send"}
              </button>
            </div>
          </section>

          {/* Column 3: logs (collapsible) */}
          <SidePanel
            token={token}
            conversationId={activeId}
            usage={usage}
            context={context}
            collapsed={sidebarCollapsed}
            setCollapsed={setSidebarCollapsed}
            showLog={showLog}
            setShowLog={setShowLog}
            showAppLogs={showAppLogs}
            setShowAppLogs={setShowAppLogs}
          />
        </div>
      )}

      <p data-testid="security-note" style={{ color: "#555", fontSize: "0.8rem" }}>
        Local-first: network egress is disabled by default; remote providers are opt-in.
      </p>
    </div>
  );
}
