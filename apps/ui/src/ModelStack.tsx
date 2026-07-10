import { useEffect, useState } from "react";

import {
  fetchModels,
  fetchProviders,
  fetchSettings,
  saveSettings,
  type ModelCapabilities,
  type ModelInfo,
  type TenantSettings,
  type TenantSettingsDefaults,
} from "./api";

// Status color code (matches the rest of the UI): green = saved, red = error, amber = unsaved edits.
const OK = "#1a7f37";
const ERR = "#b00";
const WARN = "#b06f00";

// Each row is a single combined "provider / model" choice; the <option> value encodes the pair as
// `provider<US>model` (the unit separator never appears in a provider or model name).
const SEP = "\u001f";
// The reranker runs on hf_reranker (a torch model loaded on demand) which has no list_models, so its
// options can't be auto-discovered. Curated to the Qwen3-Reranker family the provider is built and
// tested for (#492; 0.6B is the deployment default). The currently-configured id is always added on
// top of this list (see rerankerIds), so a value set out-of-band still shows and is selectable.
const RERANKER_MODELS = [
  "Qwen/Qwen3-Reranker-0.6B",
  "Qwen/Qwen3-Reranker-4B",
  "Qwen/Qwen3-Reranker-8B",
];
const RERANK_OFF = "off"; // sentinel <option> value: reranking explicitly disabled

// A provider and the models it offers (with capabilities), used to build the per-task combined lists.
interface ProviderModels {
  provider: string;
  models: ModelInfo[];
}

interface ComboOption {
  value: string;
  label: string;
  provider: string;
  model: string;
}

/** Build the "provider / model" options for a task, filtered to models with capability ``cap``, and
 *  always including the currently-selected pair (so a configured-but-unlisted model still shows). */
function comboOptions(
  providerModels: ProviderModels[],
  cap: keyof ModelCapabilities,
  current: { provider: string | null; model: string | null },
  onlyProvider?: string,
): ComboOption[] {
  const opts: ComboOption[] = [];
  for (const pm of providerModels) {
    if (onlyProvider && pm.provider !== onlyProvider) continue;
    for (const m of pm.models) {
      if (m.capabilities[cap]) {
        opts.push({ value: pm.provider + SEP + m.name, label: `${pm.provider} / ${m.name}`, provider: pm.provider, model: m.name });
      }
    }
  }
  if (current.provider && current.model && !opts.some((o) => o.provider === current.provider && o.model === current.model)) {
    opts.unshift({
      value: current.provider + SEP + current.model,
      label: `${current.provider} / ${current.model}`,
      provider: current.provider,
      model: current.model,
    });
  }
  return opts;
}

/** Per-task model defaults for every AI/LLM stage in the stack (#491): the provider+model the backend
 *  uses when no per-turn override is set. One combined "provider / model" dropdown per task. */
export function ModelStack({ token }: { token: string }): React.ReactElement {
  const [draft, setDraft] = useState<TenantSettings | null>(null);
  const [defaults, setDefaults] = useState<TenantSettingsDefaults | null>(null);
  const [providerModels, setProviderModels] = useState<ProviderModels[]>([]);
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

  // Fetch each provider's models (with capabilities) so the rows can offer real "provider / model"
  // combinations filtered per task. Best-effort + per-provider isolated: one provider erroring (e.g.
  // an unreachable remote) still yields the others.
  useEffect(() => {
    let cancelled = false;
    fetchProviders(token)
      .then(({ providers }) =>
        Promise.all(
          providers.map((p) =>
            fetchModels(token, p)
              .then(({ models }) => ({ provider: p, models }))
              .catch(() => ({ provider: p, models: [] as ModelInfo[] })),
          ),
        ),
      )
      .then((pm) => {
        if (!cancelled) setProviderModels(pm);
      })
      .catch(() => {
        if (!cancelled) setProviderModels([]);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  function patch(update: Partial<TenantSettings>): void {
    if (draft === null) return;
    setDraft({ ...draft, ...update });
    setDirty(true);
    setSaved(false);
  }

  // The combined dropdowns set both the provider and model fields from one <option>; an empty value
  // clears both back to "use server default".
  function setChatModel(value: string): void {
    const [provider, model] = value ? value.split(SEP) : [null, null];
    patch({ model_provider: provider as "ollama" | "openai_compat" | null, default_model: model });
  }
  function setEmbedModel(value: string): void {
    const [provider, model] = value ? value.split(SEP) : [null, null];
    patch({ embed_provider: provider as "ollama" | "openai_compat" | null, embed_model: model });
  }
  // NER runs on Ollama (no ner_provider field), so the dropdown writes only the model name.
  function setNerModel(value: string): void {
    const [, model] = value ? value.split(SEP) : [null, null];
    patch({ ner_model: model });
  }
  // Reranker dropdown tri-state: "" = server default (both null), RERANK_OFF = off, any id = on+id.
  function setReranker(value: string): void {
    if (value === "") patch({ rerank_enabled: null, rerank_model: null });
    else if (value === RERANK_OFF) patch({ rerank_enabled: false, rerank_model: null });
    else patch({ rerank_enabled: true, rerank_model: value });
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

  if (draft === null || defaults === null) {
    return (
      <section data-testid="model-stack-panel" aria-label="model stack">
        {error ? (
          <p data-testid="model-stack-error" style={{ color: ERR }}>
            {error}
          </p>
        ) : (
          <p style={{ color: "#888" }}>Loading…</p>
        )}
      </section>
    );
  }

  const chatOptions = comboOptions(providerModels, "text", {
    provider: draft.model_provider,
    model: draft.default_model,
  });
  const embedOptions = comboOptions(providerModels, "embeddings", {
    provider: draft.embed_provider,
    model: draft.embed_model,
  });
  const nerOptions = comboOptions(providerModels, "text", { provider: "ollama", model: draft.ner_model }, "ollama");
  const rerankValue =
    draft.rerank_enabled === true && draft.rerank_model
      ? draft.rerank_model
      : draft.rerank_enabled === false
        ? RERANK_OFF
        : "";
  const rerankerIds = [...new Set([...RERANKER_MODELS, ...(draft.rerank_model ? [draft.rerank_model] : [])])];

  // Read-only display of the deployment-configured value for each stage (from the boot CoreConfig).
  const serverChat = `${defaults.model_provider} / ${defaults.default_model}`;
  const serverEmbed = `${defaults.embed_provider} / ${defaults.embed_model}`;
  const serverRerank = defaults.rerank_enabled ? defaults.rerank_model : "Off";
  const serverNer = `ollama / ${defaults.ner_model}`;

  return (
    <section
      data-testid="model-stack-panel"
      aria-label="model stack"
      style={{ border: "1px solid #ddd", borderRadius: 8, padding: "0.75rem" }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
        <strong style={{ flex: 1 }}>Model stack</strong>
        {dirty && (
          <span data-testid="model-stack-dirty" style={{ color: WARN, fontSize: "0.8rem" }}>
            Unsaved changes
          </span>
        )}
        {saved && !dirty && (
          <span data-testid="model-stack-saved" style={{ color: OK, fontSize: "0.8rem" }}>
            Saved
          </span>
        )}
        <button data-testid="model-stack-save" onClick={() => void onSave()} disabled={!dirty}>
          Save
        </button>
      </div>

      {error && (
        <p data-testid="model-stack-error" style={{ color: ERR }}>
          {error}
        </p>
      )}

      {/* Two cards on one line: the read-only deployment defaults (left) next to your editable
          overrides (right). The override card's "Use server default" leaves a stage following the
          value shown on the left. */}
      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "stretch" }}>
        {/* Server defaults — read-only, tinted background to read as "not editable here". */}
        <fieldset
          data-testid="model-stack-server-defaults"
          style={{ flex: "1 1 260px", minWidth: 240, border: "1px solid #e2e2e2", borderRadius: 6, margin: 0, padding: "0.5rem", background: "#f6f7f9" }}
        >
          <legend style={{ fontSize: "0.8rem", color: "#555" }}>Server defaults (read-only)</legend>
          <p style={{ color: "#777", fontSize: "0.72rem", margin: "0 0 0.5rem" }}>
            What the deployment is configured to use for each stage (from the server environment).
            These apply whenever you have not set an override. Change them in the server configuration,
            not here.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "0.35rem 0.75rem", alignItems: "baseline", fontSize: "0.82rem" }}>
            <span style={{ color: "#555" }}>Chat / validation</span>
            <code data-testid="model-stack-default-chat">
              {serverChat} · reasoning {defaults.default_reasoning}
            </code>
            <span style={{ color: "#555" }}>RAG embeddings</span>
            <code data-testid="model-stack-default-embed">{serverEmbed}</code>
            <span style={{ color: "#555" }}>Reranker</span>
            <code data-testid="model-stack-default-rerank">{serverRerank}</code>
            <span style={{ color: "#555" }}>NER / relations</span>
            <code data-testid="model-stack-default-ner">{serverNer}</code>
          </div>
        </fieldset>

        {/* Model stack — your editable per-account overrides. */}
        <fieldset
          data-testid="model-stack-overrides"
          style={{ flex: "1 1 320px", minWidth: 280, border: "1px solid #e2e2e2", borderRadius: 6, margin: 0, padding: "0.5rem" }}
        >
          <legend style={{ fontSize: "0.8rem", color: "#555" }}>Model stack (your overrides)</legend>
          <p style={{ color: "#777", fontSize: "0.72rem", margin: "0 0 0.5rem" }}>
            A choice here replaces the server default for that stage, for your account only. Each option
            is a real, available combination. Leave a stage on &ldquo;Use server default&rdquo; to keep
            following the value on the left.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "0.5rem 0.75rem", alignItems: "center", fontSize: "0.82rem" }}>
            {/* Chat / validation — provider/model + reasoning */}
            <span style={{ color: "#555" }}>Chat / validation</span>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
              <select
                data-testid="model-stack-chat"
                value={draft.model_provider && draft.default_model ? draft.model_provider + SEP + draft.default_model : ""}
                onChange={(e) => setChatModel(e.target.value)}
              >
                <option value="">Use server default</option>
                {chatOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <label style={{ fontSize: "0.78rem" }}>
                reasoning{" "}
                <select
                  data-testid="model-stack-reasoning"
                  value={draft.default_reasoning ?? ""}
                  onChange={(e) => patch({ default_reasoning: (e.target.value || null) as TenantSettings["default_reasoning"] })}
                >
                  <option value="">Use server default</option>
                  <option value="off">Off</option>
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
              </label>
            </div>

            {/* RAG embeddings — provider/model (embedding-capable) */}
            <span style={{ color: "#555" }}>RAG embeddings</span>
            <select
              data-testid="model-stack-embed"
              value={draft.embed_provider && draft.embed_model ? draft.embed_provider + SEP + draft.embed_model : ""}
              onChange={(e) => setEmbedModel(e.target.value)}
              style={{ justifySelf: "start" }}
            >
              <option value="">Use server default</option>
              {embedOptions.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>

            {/* Reranker — curated HF ids (hf_reranker can't be enumerated); "Off" disables the stage */}
            <span style={{ color: "#555" }}>Reranker</span>
            <select
              data-testid="model-stack-rerank"
              value={rerankValue}
              onChange={(e) => setReranker(e.target.value)}
              style={{ justifySelf: "start" }}
            >
              <option value="">Use server default</option>
              <option value={RERANK_OFF}>Off</option>
              {rerankerIds.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>

            {/* NER / relations — Ollama text models (provider fixed; revisit at #493 GLiNER2) */}
            <span style={{ color: "#555" }}>NER / relations</span>
            <select
              data-testid="model-stack-ner"
              value={draft.ner_model ? "ollama" + SEP + draft.ner_model : ""}
              onChange={(e) => setNerModel(e.target.value)}
              style={{ justifySelf: "start" }}
            >
              <option value="">Use server default</option>
              {nerOptions.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
        </fieldset>
      </div>
    </section>
  );
}
