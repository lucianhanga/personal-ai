import { useEffect, useState } from "react";

import { fetchTools, invokeTool, type ToolInfo, type ToolInvokeResult } from "./api";

/** List and run tools through the gateway (M5-3). */
export function Tools({ token }: { token: string }): React.ReactElement {
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [args, setArgs] = useState<string>("{}");
  const [approved, setApproved] = useState(false);
  const [grant, setGrant] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ToolInvokeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchTools(token)
      .then((t) => {
        if (!active) return;
        setTools(t);
        setSelected(t[0]?.name ?? "");
      })
      .catch((e: unknown) => active && setError(String(e)));
    return () => {
      active = false;
    };
  }, [token]);

  const tool = tools.find((t) => t.name === selected);

  async function run(): Promise<void> {
    if (!tool) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const parsed = JSON.parse(args || "{}") as Record<string, unknown>;
      const res = await invokeTool(token, {
        tool: tool.name,
        version: tool.version,
        args: parsed,
        grants: grant ? tool.permissions : [],
        approved,
      });
      setResult(res);
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      data-testid="tools-panel"
      aria-label="tools"
      style={{ border: "1px solid #ddd", borderRadius: 8, padding: "0.75rem", fontSize: "0.85rem" }}
    >
      <strong>Tools</strong>
      {error && (
        <p data-testid="tools-error" style={{ color: "#b00" }}>
          {error}
        </p>
      )}
      <ul data-testid="tool-list" style={{ margin: "0.4rem 0", paddingLeft: "1rem" }}>
        {tools.map((t) => (
          <li key={t.name} data-testid="tool-item">
            <strong>{t.name}</strong> <span style={{ color: "#888" }}>[{t.risk}]</span>
            {t.permissions.length > 0 && (
              <span style={{ color: "#b06f00" }}>
                {" "}
                · needs {t.permissions.map((p) => p.type).join(", ")}
              </span>
            )}
          </li>
        ))}
      </ul>

      <div style={{ display: "flex", gap: "0.4rem", alignItems: "center", flexWrap: "wrap" }}>
        <select
          data-testid="tool-select"
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
        >
          {tools.map((t) => (
            <option key={t.name} value={t.name}>
              {t.name}
            </option>
          ))}
        </select>
        <input
          data-testid="tool-args"
          style={{ flex: 1, fontFamily: "monospace" }}
          value={args}
          onChange={(e) => setArgs(e.target.value)}
          placeholder='{"expression": "2 + 3 * 4"}'
        />
        <label>
          <input
            data-testid="tool-grant"
            type="checkbox"
            checked={grant}
            onChange={(e) => setGrant(e.target.checked)}
          />{" "}
          grant permissions
        </label>
        <label>
          <input
            data-testid="tool-approve"
            type="checkbox"
            checked={approved}
            onChange={(e) => setApproved(e.target.checked)}
          />{" "}
          approve (high-risk)
        </label>
        <button data-testid="tool-run" onClick={() => void run()} disabled={busy || !tool}>
          {busy ? "…" : "Run"}
        </button>
      </div>

      {result && (
        <pre
          data-testid="tool-result"
          style={{
            marginTop: "0.5rem",
            background: "rgba(127,127,127,0.12)",
            padding: "0.5rem",
            borderRadius: 6,
            overflowX: "auto",
          }}
        >
          {result.ok ? JSON.stringify(result.data, null, 2) : `error: ${result.error}`}
        </pre>
      )}
    </section>
  );
}
