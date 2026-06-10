import { useEffect, useState } from "react";

import {
  checkMcpHealth,
  deleteMcpServer,
  fetchMcp,
  fetchMcpConfig,
  importMcpServers,
  putMcpConfig,
  upsertMcpServer,
  type McpConfig,
  type McpHealth,
  type McpServer,
  type McpServerInput,
} from "./api";

const MASK = "********";

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

function serverInput(s: McpServer): McpServerInput {
  return { command: s.command, args: s.args, env: s.env, enabled: s.enabled };
}

interface Editor {
  name: string;
  original: string | null; // the server name being edited (null = new)
  tab: "form" | "json";
  command: string;
  args: string;
  env: string;
  enabled: boolean;
  json: string;
}

function blankEditor(): Editor {
  return { name: "", original: null, tab: "form", command: "", args: "", env: "", enabled: true, json: "" };
}

function editorFor(s: McpServer): Editor {
  return {
    name: s.name,
    original: s.name,
    tab: "form",
    command: s.command,
    args: s.args.join(" "),
    env: envToText(s.env),
    enabled: s.enabled,
    json: "",
  };
}

function editorToInput(e: Editor): { name: string; input: McpServerInput } {
  if (e.tab === "json") {
    const parsed = JSON.parse(e.json) as McpServerInput;
    return {
      name: e.name.trim(),
      input: {
        command: String(parsed.command ?? ""),
        args: parsed.args ?? [],
        env: parsed.env ?? {},
        enabled: parsed.enabled ?? true,
      },
    };
  }
  return {
    name: e.name.trim(),
    input: {
      command: e.command.trim(),
      args: e.args.split(/\s+/).filter(Boolean),
      env: parseEnv(e.env),
      enabled: e.enabled,
    },
  };
}

function copy(text: string): void {
  void navigator.clipboard?.writeText(text);
}

function healthBadge(h: McpHealth | undefined): string {
  if (!h) return "";
  if (h.status === "healthy") return `healthy · ${h.tool_count} tools · ${h.latency_ms}ms`;
  return `${h.status}${h.error ? `: ${h.error}` : ""}`;
}

/** MCP Manager: list + Test/health, per-server Form<->JSON, whole-config JSON, import/export. */
export function McpPanel({ token }: { token: string }): React.ReactElement {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [health, setHealth] = useState<Record<string, McpHealth>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [importText, setImportText] = useState<string | null>(null);
  const [configText, setConfigText] = useState<string | null>(null); // whole-config editor

  function reload(): void {
    fetchMcp(token)
      .then((s) => {
        setServers(s);
        setError(null);
      })
      .catch((e: unknown) => setError(String(e)));
  }
  useEffect(reload, [token]);

  async function withBusy(fn: () => Promise<void>): Promise<void> {
    setBusy(true);
    try {
      await fn();
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  function openForm(server?: McpServer): void {
    setEditor(server ? editorFor(server) : blankEditor());
  }

  // Switch editor tabs, carrying the data across (invalid JSON blocks the switch).
  function switchTab(to: "form" | "json"): void {
    if (!editor) return;
    if (to === "json") {
      const { input } = editorToInput({ ...editor, tab: "form" });
      setEditor({ ...editor, tab: "json", json: JSON.stringify(input, null, 2) });
      return;
    }
    try {
      const parsed = JSON.parse(editor.json) as McpServerInput;
      setEditor({
        ...editor,
        tab: "form",
        command: String(parsed.command ?? ""),
        args: (parsed.args ?? []).join(" "),
        env: envToText(parsed.env ?? {}),
        enabled: parsed.enabled ?? true,
      });
    } catch (e: unknown) {
      setError(`invalid JSON, fix it before switching to Form: ${e}`);
    }
  }

  async function saveEditor(): Promise<void> {
    if (!editor) return;
    let name: string;
    let input: McpServerInput;
    try {
      ({ name, input } = editorToInput(editor));
    } catch (e: unknown) {
      setError(`invalid JSON: ${e}`);
      return;
    }
    if (!name || !input.command.trim()) {
      setError("name and command are required");
      return;
    }
    if (input.enabled && !window.confirm(`Connect "${name}"? This runs a program on your machine.`))
      return;
    await withBusy(async () => {
      if (editor.original && editor.original !== name) await deleteMcpServer(token, editor.original);
      await upsertMcpServer(token, name, input);
      setEditor(null);
      reload();
    });
  }

  async function toggle(s: McpServer): Promise<void> {
    if (!s.enabled && !window.confirm(`Connect "${s.name}"? This runs a program on your machine.`))
      return;
    await withBusy(async () => {
      await upsertMcpServer(token, s.name, { ...serverInput(s), enabled: !s.enabled });
      reload();
    });
  }

  async function test(name: string): Promise<void> {
    await withBusy(async () => {
      const h = await checkMcpHealth(token, name);
      setHealth((prev) => ({ ...prev, [name]: h }));
    });
  }

  async function remove(name: string): Promise<void> {
    if (!window.confirm(`Remove MCP server "${name}"?`)) return;
    await withBusy(async () => {
      await deleteMcpServer(token, name);
      reload();
    });
  }

  async function runImport(): Promise<void> {
    if (importText === null) return;
    let map: McpConfig;
    try {
      const parsed = JSON.parse(importText);
      map = (parsed.mcpServers ?? parsed) as McpConfig;
      if (typeof map !== "object" || Array.isArray(map) || Object.keys(map).length === 0)
        throw new Error("expected an mcpServers object");
    } catch (e: unknown) {
      setError(`invalid JSON: ${e}`);
      return;
    }
    if (!window.confirm("Import & connect these servers? They run programs on your machine.")) return;
    await withBusy(async () => {
      await importMcpServers(token, map);
      setImportText(null);
      reload();
    });
  }

  async function openConfig(): Promise<void> {
    await withBusy(async () => {
      const cfg = await fetchMcpConfig(token);
      setConfigText(JSON.stringify({ mcpServers: cfg }, null, 2));
    });
  }

  async function applyConfig(): Promise<void> {
    if (configText === null) return;
    let map: McpConfig;
    try {
      const parsed = JSON.parse(configText);
      map = (parsed.mcpServers ?? parsed) as McpConfig;
    } catch (e: unknown) {
      setError(`invalid JSON: ${e}`);
      return;
    }
    if (!window.confirm("Apply this config? Removed servers are disconnected; new ones run programs."))
      return;
    await withBusy(async () => {
      await putMcpConfig(token, map);
      setConfigText(null);
      reload();
    });
  }

  function exportAll(): void {
    const cfg: McpConfig = Object.fromEntries(servers.map((s) => [s.name, serverInput(s)]));
    copy(JSON.stringify({ mcpServers: cfg }, null, 2));
    setError(null);
  }

  return (
    <section
      data-testid="mcp-manager"
      aria-label="MCP servers"
      style={{ border: "1px solid #ddd", borderRadius: 8, padding: "0.75rem", fontSize: "0.8rem" }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", flexWrap: "wrap" }}>
        <strong style={{ flex: 1 }}>MCP servers</strong>
        <button data-testid="mcp-add" onClick={() => openForm()} disabled={busy}>
          + Add
        </button>
        <button data-testid="mcp-import-open" onClick={() => setImportText("")} disabled={busy}>
          Import
        </button>
        <button data-testid="mcp-edit-all" onClick={() => void openConfig()} disabled={busy}>
          Edit JSON
        </button>
        <button data-testid="mcp-export-all" onClick={exportAll} disabled={busy || !servers.length}>
          Export
        </button>
      </div>

      {error && (
        <p data-testid="mcp-error" style={{ color: "#b00", whiteSpace: "pre-wrap" }}>
          {error}
        </p>
      )}
      {servers.length === 0 && !editor && importText === null && configText === null && (
        <p data-testid="mcp-empty" style={{ color: "#888" }}>
          No MCP servers yet. “+ Add” one, or “Import” a JSON block (Playwright, MarkItDown, Tavily…).
        </p>
      )}

      <ul style={{ listStyle: "none", margin: "0.5rem 0 0", padding: 0 }}>
        {servers.map((s) => (
          <li
            key={s.name}
            data-testid="mcp-server"
            style={{ borderTop: "1px solid #eee", padding: "0.4rem 0" }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "0.3rem", flexWrap: "wrap" }}>
              <span style={{ color: s.connected ? "#2a7" : s.error ? "#b00" : "#888" }}>
                {s.connected ? "✓" : s.error ? "✗" : "○"}
              </span>
              <strong style={{ flex: 1 }}>{s.name}</strong>
              <button data-testid="mcp-test" onClick={() => void test(s.name)} disabled={busy}>
                Test
              </button>
              <button data-testid="mcp-toggle" onClick={() => void toggle(s)} disabled={busy}>
                {s.enabled ? "Disconnect" : "Connect"}
              </button>
              <button data-testid="mcp-edit" onClick={() => openForm(s)} disabled={busy}>
                Edit
              </button>
              <button
                data-testid="mcp-export"
                onClick={() => copy(JSON.stringify({ [s.name]: serverInput(s) }, null, 2))}
                disabled={busy}
                title="Copy this server's JSON"
              >
                Copy
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
              {health[s.name] && (
                <span data-testid="mcp-health" style={{ marginLeft: "0.5rem", color: "#357" }}>
                  · {healthBadge(health[s.name])}
                </span>
              )}
            </div>
            {s.tools.length > 0 && (
              <div style={{ color: "#555", whiteSpace: "pre-wrap" }}>{s.tools.join(", ")}</div>
            )}
          </li>
        ))}
      </ul>

      {editor && (
        <div
          data-testid="mcp-form"
          style={{ borderTop: "1px solid #ddd", marginTop: "0.5rem", paddingTop: "0.5rem" }}
        >
          <div style={{ display: "flex", gap: "0.4rem", marginBottom: 4 }}>
            <button
              data-testid="mcp-tab-form"
              onClick={() => switchTab("form")}
              style={{ fontWeight: editor.tab === "form" ? "bold" : "normal" }}
            >
              Form
            </button>
            <button
              data-testid="mcp-tab-json"
              onClick={() => switchTab("json")}
              style={{ fontWeight: editor.tab === "json" ? "bold" : "normal" }}
            >
              JSON
            </button>
          </div>
          <input
            data-testid="mcp-form-name"
            placeholder="name (e.g. playwright)"
            value={editor.name}
            onChange={(e) => setEditor({ ...editor, name: e.target.value })}
            style={{ width: "100%", marginBottom: 4 }}
          />
          {editor.tab === "form" ? (
            <>
              <input
                data-testid="mcp-form-command"
                placeholder="command (e.g. npx)"
                value={editor.command}
                onChange={(e) => setEditor({ ...editor, command: e.target.value })}
                style={{ width: "100%", marginBottom: 4 }}
              />
              <input
                data-testid="mcp-form-args"
                placeholder="args (space-separated)"
                value={editor.args}
                onChange={(e) => setEditor({ ...editor, args: e.target.value })}
                style={{ width: "100%", marginBottom: 4 }}
              />
              <textarea
                data-testid="mcp-form-env"
                placeholder="env, one KEY=value per line (leave ******** to keep a secret)"
                value={editor.env}
                onChange={(e) => setEditor({ ...editor, env: e.target.value })}
                rows={3}
                style={{ width: "100%", marginBottom: 4 }}
              />
              <label style={{ display: "block", marginBottom: 4 }}>
                <input
                  data-testid="mcp-form-enabled"
                  type="checkbox"
                  checked={editor.enabled}
                  onChange={(e) => setEditor({ ...editor, enabled: e.target.checked })}
                />{" "}
                Connect now (runs the program)
              </label>
            </>
          ) : (
            <textarea
              data-testid="mcp-json-text"
              value={editor.json}
              onChange={(e) => setEditor({ ...editor, json: e.target.value })}
              rows={8}
              style={{ width: "100%", marginBottom: 4, fontFamily: "monospace" }}
            />
          )}
          <div style={{ display: "flex", gap: "0.4rem" }}>
            <button data-testid="mcp-form-save" onClick={() => void saveEditor()} disabled={busy}>
              Save
            </button>
            <button data-testid="mcp-form-cancel" onClick={() => setEditor(null)} disabled={busy}>
              Cancel
            </button>
          </div>
          <div style={{ color: "#888", marginTop: 4 }}>Secrets show as {MASK}; leave them to keep.</div>
        </div>
      )}

      {importText !== null && (
        <div
          data-testid="mcp-import"
          style={{ borderTop: "1px solid #ddd", marginTop: "0.5rem", paddingTop: "0.5rem" }}
        >
          <div style={{ color: "#888", marginBottom: 4 }}>Paste an mcpServers JSON block:</div>
          <textarea
            data-testid="mcp-import-text"
            value={importText}
            onChange={(e) => setImportText(e.target.value)}
            rows={6}
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

      {configText !== null && (
        <div
          data-testid="mcp-config"
          style={{ borderTop: "1px solid #ddd", marginTop: "0.5rem", paddingTop: "0.5rem" }}
        >
          <div style={{ color: "#888", marginBottom: 4 }}>
            Whole config — edit all servers, then Apply (replaces the config; secrets shown as {MASK}):
          </div>
          <textarea
            data-testid="mcp-config-text"
            value={configText}
            onChange={(e) => setConfigText(e.target.value)}
            rows={12}
            style={{ width: "100%", marginBottom: 4, fontFamily: "monospace" }}
          />
          <div style={{ display: "flex", gap: "0.4rem" }}>
            <button data-testid="mcp-config-apply" onClick={() => void applyConfig()} disabled={busy}>
              Apply
            </button>
            <button data-testid="mcp-config-cancel" onClick={() => setConfigText(null)} disabled={busy}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
