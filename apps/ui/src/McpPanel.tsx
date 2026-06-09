import { useEffect, useState } from "react";

import { fetchMcp, type McpServer } from "./api";

/** Configured MCP servers: connect status + the tools each exposed (behind the gateway). */
export function McpPanel({ token }: { token: string }): React.ReactElement {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function reload(): void {
    setLoading(true);
    fetchMcp(token)
      .then((s) => {
        setServers(s);
        setError(null);
      })
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(reload, [token]);

  return (
    <section
      data-testid="mcp-panel"
      aria-label="MCP servers"
      style={{ border: "1px solid #ddd", borderRadius: 8, padding: "0.75rem", fontSize: "0.8rem" }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <strong style={{ flex: 1 }}>MCP servers</strong>
        <button data-testid="mcp-refresh" onClick={reload}>
          Refresh
        </button>
      </div>

      {error && (
        <p data-testid="mcp-error" style={{ color: "#b00" }}>
          {error}
        </p>
      )}
      {loading && <p style={{ color: "#888" }}>Loading…</p>}
      {!loading && servers.length === 0 && (
        <p data-testid="mcp-empty" style={{ color: "#888" }}>
          No MCP servers configured. Set PERSONALAI_MCP_CONFIG to an mcp.json and restart.
        </p>
      )}

      <ul style={{ listStyle: "none", margin: "0.5rem 0 0", padding: 0 }}>
        {servers.map((s) => (
          <li
            key={s.name}
            data-testid="mcp-server"
            style={{ borderTop: "1px solid #eee", padding: "0.35rem 0" }}
          >
            <span style={{ color: s.connected ? "#2a7" : "#b00" }}>
              {s.connected ? "✓" : "✗"}
            </span>{" "}
            <strong>{s.name}</strong>{" "}
            <span style={{ color: "#888" }}>
              ({s.connected ? `${s.tools.length} tool${s.tools.length === 1 ? "" : "s"}` : "error"})
            </span>
            {s.error && <div style={{ color: "#b00" }}>{s.error}</div>}
            {s.tools.length > 0 && (
              <div style={{ color: "#555", whiteSpace: "pre-wrap" }}>{s.tools.join(", ")}</div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
