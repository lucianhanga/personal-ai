import { useEffect, useState } from "react";

import {
  deleteMemory,
  fetchMemories,
  forgetAllMemory,
  updateMemory,
  type MemoryItem,
} from "./api";

// When each memory was saved (and whether it has since been edited), for the UI (#314).
function savedLabel(m: MemoryItem): string {
  const created = new Date(m.created_at);
  if (Number.isNaN(created.getTime())) return "";
  const when = created.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
  const edited = new Date(m.updated_at).getTime() - created.getTime() > 1000;
  return edited ? `Saved ${when} · edited` : `Saved ${when}`;
}

/** Visualise and erase long-term memory (M4-4). */
export function Memory({ token }: { token: string }): React.ReactElement {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  function reload(): void {
    setLoading(true);
    fetchMemories(token)
      .then((m) => {
        setItems(m);
        setError(null);
      })
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(reload, [token]);

  async function onSave(id: string): Promise<void> {
    try {
      await updateMemory(token, id, draft);
      setEditing(null);
      reload();
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  async function onDelete(id: string): Promise<void> {
    try {
      await deleteMemory(token, id);
      setItems(items.filter((m) => m.id !== id));
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  async function onForgetAll(): Promise<void> {
    if (!window.confirm("Forget everything PersonalAI remembers about you?")) return;
    try {
      await forgetAllMemory(token);
      setItems([]);
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  return (
    <section
      data-testid="memory-panel"
      aria-label="memory"
      style={{ border: "1px solid #ddd", borderRadius: 8, padding: "0.75rem" }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <strong style={{ flex: 1 }}>What PersonalAI remembers</strong>
        <button data-testid="memory-refresh" onClick={reload}>
          Refresh
        </button>
        <button
          data-testid="memory-forget-all"
          onClick={() => void onForgetAll()}
          disabled={items.length === 0}
        >
          Forget everything
        </button>
      </div>

      {error && (
        <p data-testid="memory-error" style={{ color: "#b00" }}>
          {error}
        </p>
      )}
      {loading && <p style={{ color: "#888" }}>Loading…</p>}
      {!loading && items.length === 0 && (
        <p data-testid="memory-empty" style={{ color: "#888" }}>
          Nothing remembered yet. Chat with “Use my memory” on and durable facts will appear here.
        </p>
      )}

      <ul style={{ listStyle: "none", margin: "0.5rem 0 0", padding: 0 }}>
        {items.map((m) => (
          <li
            key={m.id}
            data-testid="memory-item"
            style={{ borderTop: "1px solid #eee", padding: "0.4rem 0" }}
          >
            {editing === m.id ? (
              <span style={{ display: "flex", gap: "0.4rem" }}>
                <input
                  data-testid="memory-edit-input"
                  style={{ flex: 1 }}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                />
                <button data-testid={`memory-save-${m.id}`} onClick={() => void onSave(m.id)}>
                  Save
                </button>
                <button onClick={() => setEditing(null)}>Cancel</button>
              </span>
            ) : (
              <span style={{ display: "flex", gap: "0.4rem", alignItems: "baseline" }}>
                <span style={{ flex: 1 }}>
                  <span style={{ fontSize: "0.7rem", color: "#888" }}>[{m.kind}]</span> {m.text}
                  <span
                    data-testid={`memory-saved-${m.id}`}
                    style={{ display: "block", fontSize: "0.7rem", color: "#aaa" }}
                  >
                    {savedLabel(m)}
                  </span>
                </span>
                <button
                  data-testid={`memory-edit-${m.id}`}
                  onClick={() => {
                    setEditing(m.id);
                    setDraft(m.text);
                  }}
                >
                  Edit
                </button>
                <button data-testid={`memory-delete-${m.id}`} onClick={() => void onDelete(m.id)}>
                  Delete
                </button>
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
