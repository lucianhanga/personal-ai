import { useEffect, useState } from "react";

import { AgentCollaborationGraph } from "./AgentGraph";
import { AGENT_BG, AGENT_FG } from "./agentColors";
import {
  fetchAgentConfig,
  fetchSettings,
  saveAgentConfig,
  saveSettings,
  type AgentConfigView,
  type AgentGraphConfig,
  type TenantSettings,
} from "./api";

// Status color code (green = saved, red = error, amber = unsaved), matching the rest of the UI.
const OK = "#1a7f37";
const ERR = "#b00";
const WARN = "#b06f00";

type Mode = "single" | "multi" | "custom";

// Per-agent editable draft, keyed by agent name.
interface AgentDraft {
  prompt: string; // "" = inherit the default
  disabled: Set<string>; // tool/MCP names disabled for this agent
}

const MODES: { value: Mode; label: string; desc: string; disabled?: boolean }[] = [
  { value: "single", label: "Single agent", desc: "One tool-calling loop. Simple and fast." },
  {
    value: "multi",
    label: "Multi-agent graph",
    desc: "planner -> researcher -> critic -> [gate] -> finalize.",
  },
  {
    value: "custom",
    label: "Custom (coming soon)",
    desc: "Define your own agents and how they communicate.",
    disabled: true,
  },
];

/** Configure the agentic mode and, for the multi-agent graph, each agent's prompt + tools (#290). */
export function Agents({ token }: { token: string }): React.ReactElement {
  const [settings, setSettings] = useState<TenantSettings | null>(null);
  const [view, setView] = useState<AgentConfigView | null>(null);
  const [drafts, setDrafts] = useState<Record<string, AgentDraft>>({});
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reload(): void {
    Promise.all([fetchSettings(token), fetchAgentConfig(token)])
      .then(([s, v]) => {
        setSettings(s.settings);
        setView(v);
        const next: Record<string, AgentDraft> = {};
        for (const a of v.agents) {
          const saved = v.config.agents.find((c) => c.name === a.name);
          next[a.name] = {
            prompt: saved?.prompt ?? "",
            disabled: new Set(saved?.disabled_tools ?? []),
          };
        }
        setDrafts(next);
        setError(null);
        setDirty(false);
        setSaved(false);
      })
      .catch((e: unknown) => setError(String(e)));
  }

  useEffect(reload, [token]);

  function touch(): void {
    setDirty(true);
    setSaved(false);
  }

  function setMode(mode: Mode): void {
    if (settings === null) return;
    setSettings({ ...settings, agent_mode: mode });
    touch();
  }

  function setGate(on: boolean): void {
    if (settings === null) return;
    setSettings({ ...settings, agent_human_gate: on });
    touch();
  }

  function setVerifierCheck(on: boolean): void {
    if (settings === null) return;
    setSettings({ ...settings, agent_verifier_check: on });
    touch();
  }

  function setPrompt(agent: string, prompt: string): void {
    setDrafts((d) => ({ ...d, [agent]: { ...d[agent], prompt } }));
    touch();
  }

  function toggleTool(agent: string, tool: string, enabled: boolean): void {
    setDrafts((d) => {
      const disabled = new Set(d[agent].disabled);
      if (enabled) disabled.delete(tool);
      else disabled.add(tool);
      return { ...d, [agent]: { ...d[agent], disabled } };
    });
    touch();
  }

  async function onSave(): Promise<void> {
    if (settings === null) return;
    // Only persist agents that actually deviate from the defaults (non-empty prompt or any tool off).
    const config: AgentGraphConfig = {
      agents: Object.entries(drafts)
        .filter(([, d]) => d.prompt.trim() !== "" || d.disabled.size > 0)
        .map(([name, d]) => ({
          name,
          prompt: d.prompt.trim() === "" ? null : d.prompt,
          disabled_tools: [...d.disabled],
        })),
    };
    try {
      await Promise.all([saveSettings(token, settings), saveAgentConfig(token, config)]);
      setDirty(false);
      setSaved(true);
      setError(null);
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  if (settings === null || view === null) {
    return (
      <section data-testid="agents-panel" aria-label="agents">
        {error ? (
          <p data-testid="agents-error" style={{ color: ERR }}>
            {error}
          </p>
        ) : (
          <p style={{ color: "#888" }}>Loading…</p>
        )}
      </section>
    );
  }

  const effectiveMode: Mode = (settings.agent_mode ?? "single") as Mode;

  return (
    <section
      data-testid="agents-panel"
      aria-label="agents"
      style={{ border: "1px solid #ddd", borderRadius: 8, padding: "0.75rem" }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
        <strong style={{ flex: 1 }}>Agents</strong>
        {dirty && (
          <span data-testid="agents-dirty" style={{ color: WARN, fontSize: "0.8rem" }}>
            Unsaved changes
          </span>
        )}
        {saved && !dirty && (
          <span data-testid="agents-saved" style={{ color: OK, fontSize: "0.8rem" }}>
            Saved
          </span>
        )}
        <button data-testid="agents-save" onClick={() => void onSave()} disabled={!dirty}>
          Save
        </button>
      </div>
      {error && (
        <p data-testid="agents-error" style={{ color: ERR }}>
          {error}
        </p>
      )}

      {/* Live diagram of how the team is currently wired; redraws as settings toggle. */}
      <AgentCollaborationGraph
        mode={effectiveMode}
        accuracyMode={settings.agent_accuracy_mode ?? "standard"}
        humanGate={settings.agent_human_gate ?? false}
        verifierCheck={settings.agent_verifier_check ?? true}
      />

      {/* Mode selector */}
      <fieldset
        data-testid="agents-mode"
        style={{ border: "1px solid #eee", borderRadius: 6, margin: "0 0 0.5rem", padding: "0.5rem" }}
      >
        <legend style={{ fontSize: "0.8rem", color: "#555" }}>Mode</legend>
        {MODES.map((m) => (
          <label
            key={m.value}
            style={{ display: "flex", gap: "0.5rem", alignItems: "baseline", padding: "0.2rem 0" }}
          >
            <input
              data-testid={`agents-mode-${m.value}`}
              type="radio"
              name="agent-mode"
              checked={effectiveMode === m.value}
              disabled={m.disabled}
              onChange={() => setMode(m.value)}
            />
            <span style={{ fontSize: "0.85rem", color: m.disabled ? "#aaa" : undefined }}>
              <strong>{m.label}</strong> — {m.desc}
            </span>
          </label>
        ))}
      </fieldset>

      {effectiveMode === "multi" && (
        <>
          <label style={{ display: "flex", gap: "0.5rem", alignItems: "center", padding: "0.25rem 0" }}>
            <input
              data-testid="agents-human-gate"
              type="checkbox"
              checked={settings.agent_human_gate ?? false}
              onChange={(e) => setGate(e.target.checked)}
            />
            <span style={{ fontSize: "0.85rem" }}>
              Human approval gate — pause each turn for approve/reject before finalizing
            </span>
          </label>

          <label style={{ display: "flex", gap: "0.5rem", alignItems: "center", padding: "0.25rem 0" }}>
            <input
              data-testid="agents-verifier-check"
              type="checkbox"
              checked={settings.agent_verifier_check ?? true}
              onChange={(e) => setVerifierCheck(e.target.checked)}
            />
            <span style={{ fontSize: "0.85rem" }}>
              Judge fact-check — let the final judge run one independent RAG/KAG lookup to confirm the
              answer (the verifier in accurate mode, otherwise the critic)
            </span>
          </label>

          {view.agents.map((a) => (
            <fieldset
              key={a.name}
              data-testid={`agents-card-${a.name}`}
              style={{
                // Same per-agent color code as the reasoning pane (faded bg + accent border/legend).
                border: `1px solid ${AGENT_FG[a.name] ?? "#ccc"}33`,
                background: AGENT_BG[a.name] ?? "transparent",
                borderRadius: 6,
                margin: "0.5rem 0",
                padding: "0.5rem",
              }}
            >
              <legend
                style={{
                  fontSize: "0.8rem",
                  fontWeight: 600,
                  color: AGENT_FG[a.name] ?? "#555",
                  textTransform: "capitalize",
                }}
              >
                {a.name}
              </legend>
              <textarea
                data-testid={`agents-prompt-${a.name}`}
                value={drafts[a.name]?.prompt ?? ""}
                placeholder={view.defaults[a.name]}
                onChange={(e) => setPrompt(a.name, e.target.value)}
                rows={3}
                style={{ width: "100%", boxSizing: "border-box", fontSize: "0.8rem" }}
              />
              {a.uses_tools ? (
                <div data-testid={`agents-tools-${a.name}`} style={{ marginTop: "0.35rem" }}>
                  <span style={{ fontSize: "0.75rem", color: "#555" }}>Tools / MCPs:</span>
                  {view.available_tools.length === 0 && (
                    <span style={{ fontSize: "0.75rem", color: "#888" }}> none available</span>
                  )}
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginTop: "0.2rem" }}>
                    {view.available_tools.map((t) => (
                      <label key={t} style={{ fontSize: "0.78rem", display: "flex", gap: "0.25rem" }}>
                        <input
                          data-testid={`agents-tool-${a.name}-${t}`}
                          type="checkbox"
                          checked={!drafts[a.name]?.disabled.has(t)}
                          onChange={(e) => toggleTool(a.name, t, e.target.checked)}
                        />
                        {t}
                      </label>
                    ))}
                  </div>
                </div>
              ) : (
                <p style={{ fontSize: "0.72rem", color: "#888", margin: "0.3rem 0 0" }}>
                  Tool-free (reasoning only).
                </p>
              )}
            </fieldset>
          ))}
        </>
      )}
      {effectiveMode !== "multi" && (
        <p style={{ fontSize: "0.78rem", color: "#888" }}>
          {effectiveMode === "custom"
            ? "Custom agents are not available yet."
            : "Single-agent mode runs one tool-calling loop. Switch to the multi-agent graph to configure per-agent prompts and tools."}
        </p>
      )}
    </section>
  );
}
