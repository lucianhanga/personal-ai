import { useEffect, useState } from "react";

import {
  deleteMcpServer,
  fetchMcp,
  importMcpServers,
  upsertMcpServer,
  type McpServer,
  type McpServerInput,
} from "./api";

/** Parse "KEY=value" lines into an object (blank/comment lines ignored). */
function parseEnv(text: string): Record<string, string> {
  const env: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (!t || t.startsWith("#")) continue;
    const eq = t.indexOf("=");
    if (eq > 0) env[t.slice(0, eq).trim()] = t.slice(eq + 1).trim();
  }
  return env;
}

function envToText(env: Record<string, string>): string {
  return Object.entries(env)
    .map(([k, v]) => `${k}=${v}`)
    .join("\n");
}

interface FormState {
  name: string;
  command: string;
  args: string;
  env: string;
  enabled: boolean;
}

const EMPTY: FormState = { name: "", command: "", args: "", env: "", enabled: true };

/** Manage MCP servers: list + status, add/edit (name/command/args/env), enable/disable, remove. */
export function McpPanel({ token }: { token: string }): React.ReactElement {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState<FormState | null>(null); // open editor (add or edit)
  const [importText, setImportText] = useState<string | null>(null); // open import box

  function reload(): void {
    fetchMcp(token)
      .then((s) => {
        setServers(s);
        setError(null);
      })
      .catch((e: unknown) => setError(String(e)));
  }
  useEffect(reload, [token]);

  async function save(): Promise<void> {
    if (!form) return;
    const name = form.name.trim();
    if (!name || !form.command.trim()) {
      setError("name and command are required");
      return;
    }
    if (form.enabled && !window.confirm(`Connect "${name}"? This runs a program on your machine.`)) {
      return;
    }
    setBusy(true);
    try {
      await upsertMcpServer(token, name, {
        command: form.command.trim(),
        args: form.args.split(/\s+/).filter(Boolean),
        env: parseEnv(form.env),
        enabled: form.enabled,
      });
      setForm(null);
      reload();
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function toggle(s: McpServer): Promise<void> {
    if (!s.enabled && !window.confirm(`Connect "${s.name}"? This runs a program on your machine.`)) {
      return;
    }
    setBusy(true);
    try {
      await upsertMcpServer(token, s.name, {
        command: s.command,
        args: s.args,
        env: s.env,
        enabled: !s.enabled,
      });
      reload();
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runImport(): Promise<void> {
    if (importText === null) return;
    let map: Record<string, McpServerInput>;
    try {
      const parsed = JSON.parse(importText);
      // Accept either {"mcpServers": {...}} or the bare map.
      map = (parsed.mcpServers ?? parsed.servers ?? parsed) as Record<string, McpServerInput>;
      if (typeof map !== "object" || Array.isArray(map) || Object.keys(map).length === 0) {
        throw new Error("expected an mcpServers object");
      }
    } catch (e: unknown) {
      setError(`invalid JSON: ${e}`);
      return;
    }
    if (!window.confirm("Import & connect these servers? They run programs on your machine.")) return;
    setBusy(true);
    try {
      await importMcpServers(token, map);
      setImportText(null);
      reload();
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(name: string): Promise<void> {
    if (!window.confirm(`Remove MCP server "${name}"?`)) return;
    setBusy(true);
    try {
      await deleteMcpServer(token, name);
      reload();
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  function edit(s: McpServer): void {
    setForm({
      name: s.name,
      command: s.command,
      args: s.args.join(" "),
      env: envToText(s.env),
      enabled: s.enabled,
    });
  }

  return (
    <section
      data-testid="mcp-panel"
      aria-label="MCP servers"
      style={{ border: "1px solid #ddd", borderRadius: 8, padding: "0.75rem", fontSize: "0.8rem" }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <strong style={{ flex: 1 }}>MCP servers</strong>
        <button data-testid="mcp-import-open" onClick={() => setImportText("")} disabled={busy}>
          Import
        </button>
        <button data-testid="mcp-add" onClick={() => setForm({ ...EMPTY })} disabled={busy}>
          + Add
        </button>
      </div>

      {importText !== null && (
        <div
          data-testid="mcp-import"
          style={{ borderTop: "1px solid #ddd", marginTop: "0.5rem", paddingTop: "0.5rem" }}
        >
          <div style={{ color: "#888", marginBottom: 4 }}>
            Paste an <code>mcpServers</code> JSON block (Claude Desktop format):
          </div>
          <textarea
            data-testid="mcp-import-text"
            value={importText}
            onChange={(e) => setImportText(e.target.value)}
            rows={8}
            placeholder={'{\n  "mcpServers": {\n    "time": { "command": "uvx", "args": ["mcp-server-time"] }\n  }\n}'}
            style={{ width: "100%", marginBottom: 4, fontFamily: "monospace" }}
          />
          <div style={{ display: "flex", gap: "0.4rem" }}>
            <button data-testid="mcp-import-run" onClick={() => void runImport()} disabled={busy}>
              Import &amp; connect
            </button>
            <button data-testid="mcp-import-cancel" onClick={() => setImportText(null)} disabled={busy}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && (
        <p data-testid="mcp-error" style={{ color: "#b00" }}>
          {error}
        </p>
      )}
      {servers.length === 0 && !form && (
        <p data-testid="mcp-empty" style={{ color: "#888" }}>
          No MCP servers yet. Click “+ Add” to configure one (e.g. Playwright, MarkItDown, Tavily).
        </p>
      )}

      <ul style={{ listStyle: "none", margin: "0.5rem 0 0", padding: 0 }}>
        {servers.map((s) => (
          <li
            key={s.name}
            data-testid="mcp-server"
            style={{ borderTop: "1px solid #eee", padding: "0.4rem 0" }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
              <span style={{ color: s.connected ? "#2a7" : s.error ? "#b00" : "#888" }}>
                {s.connected ? "✓" : s.error ? "✗" : "○"}
              </span>
              <strong style={{ flex: 1 }}>{s.name}</strong>
              <button data-testid="mcp-toggle" onClick={() => void toggle(s)} disabled={busy}>
                {s.enabled ? "Disconnect" : "Connect"}
              </button>
              <button data-testid="mcp-edit" onClick={() => edit(s)} disabled={busy}>
                Edit
              </button>
              <button data-testid="mcp-delete" onClick={() => void remove(s.name)} disabled={busy}>
                ✕
              </button>
            </div>
            <div style={{ color: "#888" }}>
              {s.connected
                ? `${s.tools.length} tool${s.tools.length === 1 ? "" : "s"}`
                : s.error
                  ? `error: ${s.error}`
                  : "stopped"}
            </div>
            {s.tools.length > 0 && (
              <div style={{ color: "#555", whiteSpace: "pre-wrap" }}>{s.tools.join(", ")}</div>
            )}
          </li>
        ))}
      </ul>

      {form && (
        <div
          data-testid="mcp-form"
          style={{ borderTop: "1px solid #ddd", marginTop: "0.5rem", paddingTop: "0.5rem" }}
        >
          <input
            data-testid="mcp-form-name"
            placeholder="name (e.g. playwright)"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            style={{ width: "100%", marginBottom: 4 }}
          />
          <input
            data-testid="mcp-form-command"
            placeholder="command (e.g. npx)"
            value={form.command}
            onChange={(e) => setForm({ ...form, command: e.target.value })}
            style={{ width: "100%", marginBottom: 4 }}
          />
          <input
            data-testid="mcp-form-args"
            placeholder="args (space-separated, e.g. -y @playwright/mcp@latest --headless)"
            value={form.args}
            onChange={(e) => setForm({ ...form, args: e.target.value })}
            style={{ width: "100%", marginBottom: 4 }}
          />
          <textarea
            data-testid="mcp-form-env"
            placeholder="env, one KEY=value per line (e.g. TAVILY_API_KEY=...)"
            value={form.env}
            onChange={(e) => setForm({ ...form, env: e.target.value })}
            rows={3}
            style={{ width: "100%", marginBottom: 4 }}
          />
          <label style={{ display: "block", marginBottom: 4 }}>
            <input
              data-testid="mcp-form-enabled"
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
            />{" "}
            Connect now (runs the program)
          </label>
          <div style={{ display: "flex", gap: "0.4rem" }}>
            <button data-testid="mcp-form-save" onClick={() => void save()} disabled={busy}>
              Save
            </button>
            <button data-testid="mcp-form-cancel" onClick={() => setForm(null)} disabled={busy}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
