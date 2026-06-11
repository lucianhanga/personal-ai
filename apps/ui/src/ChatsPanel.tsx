import type { Dispatch, SetStateAction } from "react";

import type { ConversationSummary } from "./api";

interface ChatsPanelProps {
  collapsed: boolean;
  setCollapsed: Dispatch<SetStateAction<boolean>>;
  conversations: ConversationSummary[];
  chats: Record<string, { busy: boolean }>;
  activeId: string | null;
  incognito: boolean;
  setIncognito: Dispatch<SetStateAction<boolean>>;
  renamingId: string | null;
  setRenamingId: Dispatch<SetStateAction<string | null>>;
  renameDraft: string;
  setRenameDraft: Dispatch<SetStateAction<string>>;
  onNewChat: () => void;
  onOpen: (id: string) => void;
  onCommitRename: (id: string) => void;
  onRemove: (id: string) => void;
}

/** Left column: the conversation list with new/open/rename/delete + incognito + collapse. */
export function ChatsPanel({
  collapsed,
  setCollapsed,
  conversations,
  chats,
  activeId,
  incognito,
  setIncognito,
  renamingId,
  setRenamingId,
  renameDraft,
  setRenameDraft,
  onNewChat,
  onOpen,
  onCommitRename,
  onRemove,
}: ChatsPanelProps): React.ReactElement {
  if (collapsed) {
    return (
      <button
        data-testid="chats-toggle"
        onClick={() => setCollapsed(false)}
        title="Show chats"
        style={{ flex: "0 0 auto", alignSelf: "flex-start" }}
      >
        Chats ›
      </button>
    );
  }
  return (
    <aside
      data-testid="chats-panel"
      style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: "0.4rem" }}
    >
      <div style={{ display: "flex", alignItems: "center" }}>
        <strong style={{ flex: 1 }}>Chats</strong>
        <button data-testid="chats-toggle" onClick={() => setCollapsed(true)} title="Collapse chats">
          ‹
        </button>
      </div>
      <button data-testid="new-chat" onClick={onNewChat}>
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
            {renamingId === c.id ? (
              <input
                data-testid={`rename-input-${c.id}`}
                autoFocus
                value={renameDraft}
                onChange={(e) => setRenameDraft(e.target.value)}
                onBlur={() => onCommitRename(c.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") onCommitRename(c.id);
                  if (e.key === "Escape") setRenamingId(null);
                }}
                style={{ flex: 1 }}
              />
            ) : (
              <>
                <button
                  data-testid={`open-${c.id}`}
                  onClick={() => onOpen(c.id)}
                  onDoubleClick={() => {
                    setRenamingId(c.id);
                    setRenameDraft(c.title);
                  }}
                  style={{
                    flex: 1,
                    textAlign: "left",
                    fontWeight: c.id === activeId ? 700 : 400,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {chats[c.id]?.busy && (
                    <span data-testid={`busy-${c.id}`} title="Generating…" aria-label="generating">
                      ⏳{" "}
                    </span>
                  )}
                  {c.title}
                </button>
                <button
                  data-testid={`rename-${c.id}`}
                  onClick={() => {
                    setRenamingId(c.id);
                    setRenameDraft(c.title);
                  }}
                  title="rename conversation"
                  style={{ fontSize: "0.7rem" }}
                >
                  ✎
                </button>
                <button
                  data-testid={`del-conv-${c.id}`}
                  onClick={() => onRemove(c.id)}
                  title="delete conversation"
                  style={{ fontSize: "0.7rem" }}
                >
                  ×
                </button>
              </>
            )}
          </span>
        ))}
      </div>
    </aside>
  );
}
