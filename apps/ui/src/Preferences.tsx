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
  placeholder?: string; // shown when the deployment default is empty (so the box isn't blank)
}

interface Group {
  title: string;
  note?: string;
  fields: FieldSpec[];
}

// Declarative layout. Field names match the backend; a blank/Default value sends null (inherit).
const GROUPS: Group[] = [
  {
    title: "Behavior",
    fields: [
      { key: "memory_enabled", label: "Long-term memory", kind: "bool" },
      { key: "grounding_enabled", label: "Grounding prompt", kind: "bool" },
      { key: "max_upload_bytes", label: "Max upload (bytes)", kind: "number" },
    ],
  },
  {
    title: "Voice (speech-to-text)",
    note: "Records voice and transcribes it. 'local' runs Whisper in-process (zero-setup, multilingual incl. Romanian; the model downloads once then runs offline — e.g. large-v3-turbo). 'openai_compat' calls a whisper server / OpenAI at the URL below. The mic appears in the composer when enabled.",
    fields: [
      { key: "transcribe_enabled", label: "Enable voice input", kind: "bool" },
      { key: "transcribe_provider", label: "Engine", kind: "enum", options: ["local", "openai_compat"] },
      { key: "transcribe_model", label: "Transcription model", kind: "text", help: "local: small/medium/large-v3-turbo · server: whisper-1" },
      { key: "transcribe_language", label: "Spoken language", kind: "enum", options: ["auto", "en", "de", "es", "ro", "fr", "it"], help: "'auto' detects the language; pin one (e.g. 'en') if it mis-detects" },
      { key: "transcribe_base_url", label: "Whisper server URL (openai_compat)", kind: "text", help: "e.g. http://127.0.0.1:8000/v1 — blank uses the OpenAI base URL", placeholder: "blank = OpenAI base URL" },
    ],
  },
  {
    title: "Voice (text-to-speech)",
    note: "Reads assistant answers aloud using your browser's built-in voices (fully local, no setup). A read-aloud control appears on each answer when enabled.",
    fields: [{ key: "tts_enabled", label: "Read answers aloud", kind: "bool" }],
  },
  {
    title: "Document indexing engine (advanced)",
    note: "How documents are embedded for search — not the chat model (that's in Settings → Agents → Defaults). Changing this re-defines indexing; existing documents were embedded with the current setting, so you may need to re-upload them. Endpoint changes apply after a backend restart.",
    fields: [
      { key: "ollama_host", label: "Ollama host", kind: "text" },
      { key: "embed_provider", label: "Index provider", kind: "enum", options: ["ollama", "openai_compat"] },
      { key: "embed_model", label: "Index embedding (advanced)", kind: "text" },
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
export function Preferences({
  token,
  onToken,
}: {
  token: string;
  onToken?: (value: string) => void;
}): React.ReactElement {
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

      {/* API token: only relevant for a backend that requires a bearer token (protected/remote
          deployments). Local zero-login and hosted cookie sessions don't need it. Kept here, out of
          the top bar, since it is a connection credential rather than a per-turn control. */}
      {onToken && (
        <fieldset
          data-testid="preferences-group-Connection"
          style={{ border: "1px solid #eee", borderRadius: 6, margin: "0 0 0.5rem", padding: "0.5rem" }}
        >
          <legend style={{ fontSize: "0.8rem", color: "#555" }}>Connection</legend>
          <label style={ROW}>
            <span style={{ flex: 1, fontSize: "0.85rem" }}>
              API token
              <span style={{ color: "#888" }}> (only if the backend requires one)</span>
            </span>
            <input
              data-testid="preferences-api-token"
              type="password"
              placeholder="PERSONALAI_AUTH_TOKEN"
              value={token}
              onChange={(e) => onToken(e.target.value)}
            />
          </label>
        </fieldset>
      )}
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
          // When the deployment default is empty/blank, fall back to the field's own hint so the
          // box reads meaningfully instead of showing nothing.
          placeholder={
            def === null || def === undefined || String(def) === ""
              ? (spec.placeholder ?? "")
              : String(def)
          }
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
