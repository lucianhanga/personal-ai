import { useEffect, useState } from "react";

import {
  fetchSettings,
  saveSettings,
  type TenantSettings,
  type TenantSettingsDefaults,
} from "./api";

// Status color code (matches the rest of the UI): green = saved, red = error, amber = unsaved edits.
const OK = "#1a7f37";
const ERR = "#b00";
const WARN = "#b06f00";

type Key = keyof TenantSettings;

interface FieldSpec {
  key: Key;
  label: string;
  kind: "text" | "number" | "bool" | "enum";
  options?: string[]; // for "enum"
  help?: string;
}

interface Group {
  title: string;
  note?: string;
  fields: FieldSpec[];
}

// Declarative layout. Field names match the backend; a blank/Default value sends null (inherit).
const GROUPS: Group[] = [
  {
    title: "Model",
    fields: [
      { key: "default_model", label: "Default model", kind: "text" },
      { key: "ollama_num_ctx", label: "Ollama context window", kind: "number" },
      { key: "ollama_keep_alive", label: "Ollama keep-alive", kind: "text", help: '"30m", "-1"' },
    ],
  },
  {
    title: "Agent",
    fields: [
      { key: "agent_graph_enabled", label: "Multi-agent graph", kind: "bool" },
      { key: "agent_human_gate", label: "Human approval gate", kind: "bool" },
      { key: "agent_accuracy_mode", label: "Accuracy mode", kind: "enum", options: ["standard", "accurate"] },
      { key: "agent_max_iterations", label: "Max tool iterations", kind: "number" },
    ],
  },
  {
    title: "Behavior",
    fields: [
      { key: "memory_enabled", label: "Long-term memory", kind: "bool" },
      { key: "grounding_enabled", label: "Grounding prompt", kind: "bool" },
      { key: "max_upload_bytes", label: "Max upload (bytes)", kind: "number" },
    ],
  },
  {
    title: "Provider (advanced)",
    note: "Provider/endpoint changes apply after the next backend restart.",
    fields: [
      { key: "model_provider", label: "Model provider", kind: "enum", options: ["ollama", "openai_compat"] },
      { key: "ollama_host", label: "Ollama host", kind: "text" },
      { key: "embed_provider", label: "Embedding provider", kind: "enum", options: ["ollama", "openai_compat"] },
      { key: "embed_model", label: "Embedding model", kind: "text" },
      { key: "openai_base_url", label: "OpenAI base URL", kind: "text" },
    ],
  },
];

const ROW: React.CSSProperties = {
  display: "flex",
  gap: "0.5rem",
  alignItems: "center",
  padding: "0.25rem 0",
};

/** Edit the tenant's preference settings (#289). Blank fields inherit the deployment default. */
export function Preferences({ token }: { token: string }): React.ReactElement {
  const [draft, setDraft] = useState<TenantSettings | null>(null);
  const [defaults, setDefaults] = useState<TenantSettingsDefaults | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reload(): void {
    fetchSettings(token)
      .then(({ settings, defaults }) => {
        setDraft(settings);
        setDefaults(defaults);
        setError(null);
        setDirty(false);
        setSaved(false);
      })
      .catch((e: unknown) => setError(String(e)));
  }

  useEffect(reload, [token]);

  function set(key: Key, value: TenantSettings[Key]): void {
    if (draft === null) return;
    setDraft({ ...draft, [key]: value });
    setDirty(true);
    setSaved(false);
  }

  async function onSave(): Promise<void> {
    if (draft === null) return;
    try {
      const stored = await saveSettings(token, draft);
      setDraft(stored);
      setDirty(false);
      setSaved(true);
      setError(null);
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  function onReset(): void {
    if (draft === null) return;
    // Clear every override back to null (inherit the deployment default).
    const cleared = Object.fromEntries(
      Object.keys(draft).map((k) => [k, null]),
    ) as unknown as TenantSettings;
    setDraft(cleared);
    setDirty(true);
    setSaved(false);
  }

  if (draft === null || defaults === null) {
    return (
      <section data-testid="preferences-panel" aria-label="preferences">
        {error ? (
          <p data-testid="preferences-error" style={{ color: ERR }}>
            {error}
          </p>
        ) : (
          <p style={{ color: "#888" }}>Loading…</p>
        )}
      </section>
    );
  }

  return (
    <section
      data-testid="preferences-panel"
      aria-label="preferences"
      style={{ border: "1px solid #ddd", borderRadius: 8, padding: "0.75rem" }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
        <strong style={{ flex: 1 }}>Preferences</strong>
        {dirty && (
          <span data-testid="preferences-dirty" style={{ color: WARN, fontSize: "0.8rem" }}>
            Unsaved changes
          </span>
        )}
        {saved && !dirty && (
          <span data-testid="preferences-saved" style={{ color: OK, fontSize: "0.8rem" }}>
            Saved
          </span>
        )}
        <button data-testid="preferences-reset" onClick={onReset}>
          Reset to defaults
        </button>
        <button data-testid="preferences-save" onClick={() => void onSave()} disabled={!dirty}>
          Save
        </button>
      </div>

      {error && (
        <p data-testid="preferences-error" style={{ color: ERR }}>
          {error}
        </p>
      )}
      <p style={{ color: "#888", fontSize: "0.75rem", margin: "0 0 0.5rem" }}>
        Blank fields inherit the deployment default (shown as the placeholder). Secrets and server
        settings are configured via environment variables, not here.
      </p>

      {GROUPS.map((group) => (
        <fieldset
          key={group.title}
          data-testid={`preferences-group-${group.title}`}
          style={{ border: "1px solid #eee", borderRadius: 6, margin: "0 0 0.5rem", padding: "0.5rem" }}
        >
          <legend style={{ fontSize: "0.8rem", color: "#555" }}>{group.title}</legend>
          {group.note && (
            <p style={{ color: WARN, fontSize: "0.72rem", margin: "0 0 0.35rem" }}>{group.note}</p>
          )}
          {group.fields.map((f) => (
            <Field
              key={f.key}
              spec={f}
              value={draft[f.key]}
              def={defaults[f.key]}
              onChange={(v) => set(f.key, v)}
            />
          ))}
        </fieldset>
      ))}
    </section>
  );
}

function Field({
  spec,
  value,
  def,
  onChange,
}: {
  spec: FieldSpec;
  value: TenantSettings[Key];
  def: TenantSettingsDefaults[Key];
  onChange: (v: TenantSettings[Key]) => void;
}): React.ReactElement {
  const tid = `preferences-${spec.key}`;
  return (
    <label style={ROW}>
      <span style={{ flex: 1, fontSize: "0.85rem" }} title={spec.help}>
        {spec.label}
      </span>
      {spec.kind === "bool" && (
        // Tri-state: Default (null), On (true), Off (false).
        <select
          data-testid={tid}
          value={value === null || value === undefined ? "" : value ? "on" : "off"}
          onChange={(e) =>
            onChange(e.target.value === "" ? null : e.target.value === "on")
          }
        >
          <option value="">Default ({def ? "on" : "off"})</option>
          <option value="on">On</option>
          <option value="off">Off</option>
        </select>
      )}
      {spec.kind === "enum" && (
        <select
          data-testid={tid}
          value={(value as string | null) ?? ""}
          onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
        >
          <option value="">Default ({String(def)})</option>
          {spec.options?.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      )}
      {(spec.kind === "text" || spec.kind === "number") && (
        <input
          data-testid={tid}
          type={spec.kind === "number" ? "number" : "text"}
          placeholder={String(def)}
          value={value === null || value === undefined ? "" : String(value)}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === "") return onChange(null);
            onChange(spec.kind === "number" ? Number(raw) : raw);
          }}
        />
      )}
    </label>
  );
}
