import { useEffect, useState } from "react";

import { fetchToolLog, type ToolLogEntry } from "./api";

/** The tool-call protocol: every gateway call (allowed + denied); click a row for details. */
export function ToolLog({ token }: { token: string }): React.ReactElement {
  const [entries, setEntries] = useState<ToolLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  function reload(): void {
    setLoading(true);
    fetchToolLog(token)
      .then((e) => {
        setEntries(e);
        setError(null);
      })
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(reload, [token]);

  return (
    <section
      data-testid="toollog-panel"
      aria-label="tool log"
      style={{ border: "1px solid #ddd", borderRadius: 8, padding: "0.75rem", fontSize: "0.8rem" }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <strong style={{ flex: 1 }}>Tool call log</strong>
        <button data-testid="toollog-refresh" onClick={reload}>
          Refresh
        </button>
      </div>

      {error && (
        <p data-testid="toollog-error" style={{ color: "#b00" }}>
          {error}
        </p>
      )}
      {loading && <p style={{ color: "#888" }}>Loading…</p>}
      {!loading && entries.length === 0 && (
        <p data-testid="toollog-empty" style={{ color: "#888" }}>
          No tool calls yet. Use a tool (or chat with “Use tools” on) and calls appear here.
        </p>
      )}

      <ul style={{ listStyle: "none", margin: "0.5rem 0 0", padding: 0 }}>
        {entries.map((e) => {
          const denied = e.type === "tool.denied";
          const isOpen = open === e.index;
          return (
            <li
              key={e.index}
              data-testid="toollog-item"
              style={{ borderTop: "1px solid #eee", padding: "0.35rem 0" }}
            >
              <button
                data-testid={`toollog-row-${e.index}`}
                onClick={() => setOpen(isOpen ? null : e.index)}
                style={{
                  width: "100%",
                  textAlign: "left",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  padding: 0,
                }}
              >
                <span style={{ color: denied ? "#b00" : e.ok ? "#2a7" : "#b06f00" }}>
                  {denied ? "✗ denied" : e.ok ? "✓ ok" : "• error"}
                </span>{" "}
                <strong>{e.tool ?? "?"}</strong>{" "}
                <span style={{ color: "#888" }}>{new Date(e.timestamp).toLocaleTimeString()}</span>
              </button>
              {isOpen && (
                <pre
                  data-testid="toollog-detail"
                  style={{
                    margin: "0.3rem 0 0",
                    background: "rgba(127,127,127,0.12)",
                    padding: "0.5rem",
                    borderRadius: 6,
                    overflowX: "auto",
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {JSON.stringify(
                    { type: e.type, tool: e.tool, args: e.args, ok: e.ok, error: e.error },
                    null,
                    2,
                  )}
                </pre>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
