import { useEffect, useState } from "react";

import { fetchLogs, type LogEntry } from "./api";

const LEVEL_COLOR: Record<string, string> = {
  ERROR: "#b00",
  CRITICAL: "#b00",
  WARNING: "#b06f00",
  INFO: "#555",
  DEBUG: "#999",
};

/** Recent backend/application logs, surfaced for visibility (M-obs). */
export function AppLogs({ token }: { token: string }): React.ReactElement {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function reload(): void {
    setLoading(true);
    fetchLogs(token)
      .then((l) => {
        setLogs(l);
        setError(null);
      })
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(reload, [token]);

  return (
    <section
      data-testid="applogs-panel"
      aria-label="application logs"
      style={{
        border: "1px solid #ddd",
        borderRadius: 8,
        padding: "0.75rem",
        fontSize: "0.78rem",
        fontFamily: "ui-monospace, monospace",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <strong style={{ flex: 1 }}>Application logs</strong>
        <button data-testid="applogs-refresh" onClick={reload}>
          Refresh
        </button>
      </div>

      {error && (
        <p data-testid="applogs-error" style={{ color: "#b00" }}>
          {error}
        </p>
      )}
      {loading && <p style={{ color: "#888" }}>Loading…</p>}
      {!loading && logs.length === 0 && (
        <p data-testid="applogs-empty" style={{ color: "#888" }}>
          No recent logs.
        </p>
      )}

      <div style={{ maxHeight: 240, overflowY: "auto", marginTop: "0.4rem" }}>
        {logs.map((l, i) => (
          <div key={i} data-testid="applogs-line" style={{ whiteSpace: "pre-wrap" }}>
            <span style={{ color: "#999" }}>{new Date(l.time).toLocaleTimeString()}</span>{" "}
            <span style={{ color: LEVEL_COLOR[l.level] ?? "#555", fontWeight: 600 }}>{l.level}</span>{" "}
            <span style={{ color: "#888" }}>{l.logger}</span> — {l.message}
          </div>
        ))}
      </div>
    </section>
  );
}
