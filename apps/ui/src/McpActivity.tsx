import { useEffect, useState } from "react";

import { fetchMcpLog, type ToolLogEntry } from "./api";

/** MCP activity: recent MCP tool calls (namespaced server.tool) from the gateway audit log. */
export function McpActivity({ token }: { token: string }): React.ReactElement {
  const [entries, setEntries] = useState<ToolLogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  function reload(): void {
    setLoading(true);
    fetchMcpLog(token)
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
      data-testid="mcp-activity"
      aria-label="MCP activity"
      role="log"
      style={{ border: "1px solid #ddd", borderRadius: 8, padding: "0.75rem", fontSize: "0.8rem" }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <strong style={{ flex: 1 }}>MCP activity</strong>
        <button data-testid="mcp-activity-refresh" onClick={reload}>
          Refresh
        </button>
      </div>
      {error && (
        <p data-testid="mcp-activity-error" style={{ color: "#b00" }}>
          {error}
        </p>
      )}
      {loading && <p style={{ color: "#888" }}>Loading…</p>}
      {!loading && entries.length === 0 && (
        <p data-testid="mcp-activity-empty" style={{ color: "#888" }}>
          No MCP tool calls yet. They appear here when the agent uses an MCP server's tools.
        </p>
      )}
      <ul style={{ listStyle: "none", margin: "0.5rem 0 0", padding: 0 }}>
        {entries.map((e) => (
          <li
            key={e.index}
            data-testid="mcp-activity-row"
            style={{ borderTop: "1px solid #eee", padding: "0.3rem 0" }}
          >
            <span style={{ color: e.ok === false ? "#b00" : "#2a7" }}>
              {e.ok === false ? "✗" : "✓"}
            </span>{" "}
            <strong>{e.tool}</strong>
            {e.error && <div style={{ color: "#b00" }}>{e.error}</div>}
            <div style={{ color: "#999" }}>{new Date(e.timestamp).toLocaleTimeString()}</div>
          </li>
        ))}
      </ul>
    </section>
  );
}
