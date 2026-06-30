import { useEffect, useState } from "react";

import { AgentCollaborationGraph } from "./AgentGraph";
import { AGENT_BG, AGENT_FG } from "./agentColors";
import {
  fetchAgentConfig,
  fetchModels,
  fetchSettings,
  saveAgentConfig,
  saveSettings,
  type AgentConfigView,
  type AgentGraphConfig,
  type ModelInfo,
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
  reasoning: string | null; // null = inherit the turn's reasoning level
  model: string | null; // null = inherit the turn's model
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
  const [availableModels, setAvailableModels] = useState<ModelInfo[]>([]);
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
            reasoning: saved?.reasoning ?? null,
            model: saved?.model ?? null,
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

  // Fetch available model ids for the per-agent model override dropdown. Best-effort: if the
  // models request fails the dropdown just shows "Inherit (turn model)" with no other options.
  useEffect(() => {
    fetchModels(token)
      .then(({ models }) => setAvailableModels(models))
      .catch(() => setAvailableModels([]));
  }, [token]);

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

  function setAgentReasoning(agent: string, value: string | null): void {
    setDrafts((d) => ({ ...d, [agent]: { ...d[agent], reasoning: value } }));
    touch();
  }

  function setAgentModel(agent: string, value: string | null): void {
    setDrafts((d) => ({ ...d, [agent]: { ...d[agent], model: value } }));
    touch();
  }

  function setDefaultProvider(value: string | null): void {
    if (settings === null) return;
    setSettings({ ...settings, model_provider: value as "ollama" | "openai_compat" | null });
    touch();
  }

  function setDefaultModel(value: string | null): void {
    if (settings === null) return;
    setSettings({ ...settings, default_model: value });
    touch();
  }

  function setDefaultReasoning(value: string | null): void {
    if (settings === null) return;
    setSettings({ ...settings, default_reasoning: value as "off" | "low" | "medium" | "high" | null });
    touch();
  }

  function setAccuracyMode(value: string | null): void {
    if (settings === null) return;
    setSettings({ ...settings, agent_accuracy_mode: value as "standard" | "accurate" | null });
    touch();
  }

  function setMaxIterations(value: number | null): void {
    if (settings === null) return;
    setSettings({ ...settings, agent_max_iterations: value });
    touch();
  }

  function setTimeoutSeconds(value: number | null): void {
    if (settings === null) return;
    setSettings({ ...settings, agent_timeout_seconds: value });
    touch();
  }

  async function onSave(): Promise<void> {
    if (settings === null) return;
    // Only persist agents that actually deviate from the defaults (non-empty prompt, any tool
    // disabled, or a reasoning/model override set).
    const config: AgentGraphConfig = {
      agents: Object.entries(drafts)
        .filter(([, d]) => d.prompt.trim() !== "" || d.disabled.size > 0 || d.reasoning !== null || d.model !== null)
        .map(([name, d]) => ({
          name,
          prompt: d.prompt.trim() === "" ? null : d.prompt,
          disabled_tools: [...d.disabled],
          reasoning: d.reasoning,
          model: d.model,
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

      {/* Global defaults: provider, model, and reasoning level the backend applies when no per-turn override is set. */}
      <fieldset
        data-testid="agents-defaults"
        style={{ border: "1px solid #eee", borderRadius: 6, margin: "0 0 0.5rem", padding: "0.5rem" }}
      >
        <legend style={{ fontSize: "0.8rem", color: "#555" }}>Defaults</legend>
        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          <label style={{ fontSize: "0.78rem" }}>
            Provider{" "}
            <select
              data-testid="agents-default-provider"
              value={settings.model_provider ?? ""}
              onChange={(e) => setDefaultProvider(e.target.value || null)}
            >
              <option value="">Use server default</option>
              <option value="ollama">ollama</option>
              <option value="openai_compat">openai_compat</option>
            </select>
          </label>
          <label style={{ fontSize: "0.78rem" }}>
            Default model{" "}
            <select
              data-testid="agents-default-model"
              value={settings.default_model ?? ""}
              onChange={(e) => setDefaultModel(e.target.value || null)}
            >
              <option value="">Use server default</option>
              {availableModels.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}
                </option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: "0.78rem" }}>
            Default reasoning{" "}
            <select
              data-testid="agents-default-reasoning"
              value={settings.default_reasoning ?? ""}
              onChange={(e) => setDefaultReasoning(e.target.value || null)}
            >
              <option value="">Inherit (server default)</option>
              <option value="off">Off</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </label>
        </div>
      </fieldset>

      {/* Execution knobs that apply to every mode. Accuracy mode drives the verification ladder
          depth (verifier vs critic) shown in the graph above; max-iterations and timeout bound a
          single turn. Moved here from Preferences (#513) so all agent config lives in one panel. */}
      <fieldset
        data-testid="agents-execution"
        style={{ border: "1px solid #eee", borderRadius: 6, margin: "0 0 0.5rem", padding: "0.5rem" }}
      >
        <legend style={{ fontSize: "0.8rem", color: "#555" }}>Execution</legend>
        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          <label style={{ fontSize: "0.78rem" }}>
            Accuracy mode{" "}
            <select
              data-testid="agents-accuracy-mode"
              value={settings.agent_accuracy_mode ?? ""}
              onChange={(e) => setAccuracyMode(e.target.value || null)}
            >
              <option value="">Inherit (server default)</option>
              <option value="standard">standard</option>
              <option value="accurate">accurate</option>
            </select>
          </label>
          <label style={{ fontSize: "0.78rem" }}>
            Max tool iterations{" "}
            <input
              data-testid="agents-max-iterations"
              type="number"
              placeholder="server default"
              value={settings.agent_max_iterations ?? ""}
              onChange={(e) => setMaxIterations(e.target.value === "" ? null : Number(e.target.value))}
              style={{ width: "5rem" }}
            />
          </label>
          <label style={{ fontSize: "0.78rem" }}>
            Turn timeout (seconds){" "}
            <input
              data-testid="agents-timeout-seconds"
              type="number"
              placeholder="server default"
              value={settings.agent_timeout_seconds ?? ""}
              onChange={(e) => setTimeoutSeconds(e.target.value === "" ? null : Number(e.target.value))}
              style={{ width: "6rem" }}
            />
          </label>
        </div>
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
              Judge fact-check — let the final judge independently confirm the answer (a RAG/KAG/memory
              lookup plus a bounded verify-only tool re-check; verifier in accurate mode, else the critic)
            </span>
          </label>

          <div
            data-testid="agents-cards"
            style={{
              // Two cards per row so each prompt textarea is a comfortable reading width rather than
              // the full window. align-items:start lets the taller Researcher card (it has the
              // tools list) not stretch its row-mate. Cards stay full-width controls within a column.
              display: "grid",
              gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
              gap: "0.6rem",
              alignItems: "start",
            }}
          >
            {view.agents.map((a) => (
              <fieldset
                key={a.name}
                data-testid={`agents-card-${a.name}`}
              style={{
                // Same per-agent color code as the reasoning pane (faded bg + accent border/legend).
                border: `1px solid ${AGENT_FG[a.name] ?? "#ccc"}33`,
                background: AGENT_BG[a.name] ?? "transparent",
                borderRadius: 6,
                margin: 0,
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
              <div style={{ display: "flex", gap: "1rem", marginTop: "0.35rem", flexWrap: "wrap" }}>
                <label style={{ fontSize: "0.78rem" }}>
                  Reasoning{" "}
                  <select
                    data-testid={`agents-reasoning-${a.name}`}
                    value={drafts[a.name]?.reasoning ?? ""}
                    onChange={(e) => setAgentReasoning(a.name, e.target.value || null)}
                  >
                    <option value="">Inherit (default)</option>
                    <option value="off">Off</option>
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                </label>
                <label style={{ fontSize: "0.78rem" }}>
                  Model{" "}
                  <select
                    data-testid={`agents-model-${a.name}`}
                    value={drafts[a.name]?.model ?? ""}
                    onChange={(e) => setAgentModel(a.name, e.target.value || null)}
                  >
                    <option value="">Inherit (turn model)</option>
                    {availableModels.map((m) => (
                      <option key={m.name} value={m.name}>
                        {m.name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
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
          </div>
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
