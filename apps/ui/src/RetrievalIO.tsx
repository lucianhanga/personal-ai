import { useState } from "react";

// RAG-pipeline chip components (#437). Three thin ResourceIO-style chips share the same disclosure
// shell (caret + category word + label + right-aligned status pill; Tier-2 detail). `retrieval` is
// the info-rich one (the compact citation list); `indexing` + `ner` are simple key/value chips. We
// keep them in one module so the shared shell isn't forked across files.

const INDEXING = "#8a6d00"; // deep amber-olive — AA ~5.6:1 on white (UX-owned)
const RETRIEVAL = "#1558b0"; // royal indigo — AA ~6.4:1; deeper than context's accent #4a90d9
const NER = "#a21caf"; // fuchsia-plum — AA ~5.2:1; distinct from tool violet #7c3aed
const OK = "#1a7f37"; // green — done
const ERR = "#b00020"; // red — error
const WARN = "#b06f00"; // amber — in progress
// Muted text a user must READ uses #6b7280 (AA); #888/#999 stay decorative (codebase rule).
const READABLE = "#6b7280";

// A pipeline chip's lifecycle state, derived by the caller from the trace item's status.
export type PipelineState = "in-progress" | "done" | "error";

// ms -> short human duration; mirrors ResourceIO/ActivityTimeline so the panel reads consistently.
function fmtMs(ms: number): string {
  return ms < 1000
    ? `${Math.round(ms)} ms`
    : ms < 60000
      ? `${(ms / 1000).toFixed(1)} s`
      : `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}

function clip(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

/** The Tier-1 status pill: words + color (never color-only). green done / red error / amber live. */
function StatusPill({ state }: { state: PipelineState }): React.ReactElement {
  const map = {
    "in-progress": { color: WARN, bg: "rgba(176,111,0,0.10)", text: "in progress" },
    done: { color: OK, bg: "rgba(26,127,55,0.12)", text: "done" },
    error: { color: ERR, bg: "rgba(176,0,32,0.10)", text: "error" },
  } as const;
  const { color, bg, text } = map[state];
  return (
    <span
      data-testid="pipelineio-status"
      style={{ color, background: bg, borderRadius: 8, padding: "0 0.4rem", fontSize: "0.72rem", fontWeight: 600 }}
    >
      {text}
    </span>
  );
}

/** The shared chip shell: caret + category word (hue) + label + status pill; Tier-2 children. */
function Chip({
  testid,
  bg,
  hue,
  category,
  label,
  state,
  children,
  defaultOpen = false,
}: {
  testid: string;
  bg: string;
  hue: string;
  category: string;
  label: string;
  state: PipelineState;
  children?: React.ReactNode;
  defaultOpen?: boolean;
}): React.ReactElement {
  const [open, setOpen] = useState<boolean>(defaultOpen);
  return (
    <div data-testid={testid} data-status={state} style={{ background: bg, borderRadius: 3, padding: "1px 5px", margin: "1px 0" }}>
      <button
        data-testid="pipelineio-summary"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.4rem",
          width: "100%",
          background: "none",
          border: "none",
          cursor: "pointer",
          padding: "1px 0",
          textAlign: "left",
          font: "inherit",
        }}
      >
        <span aria-hidden style={{ color: READABLE, fontSize: "0.72rem" }}>{open ? "▾" : "▸"}</span>
        <span style={{ color: hue, fontWeight: 600 }}>{category}</span>
        <span style={{ color: "#1f2937", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {label}
        </span>
        <span style={{ marginLeft: "auto", flex: "0 0 auto" }}>
          <StatusPill state={state} />
        </span>
      </button>
      {open && children != null && (
        <div data-testid="pipelineio-detail" style={{ paddingLeft: "0.9rem", paddingBottom: "0.25rem" }}>
          {children}
        </div>
      )}
    </div>
  );
}

/** A muted `Label: value` row, matching ResourceIO's Tier-2 rows. */
function Row({ label, value }: { label: string; value: string }): React.ReactElement {
  return (
    <div style={{ color: READABLE, fontSize: "0.78rem" }}>
      <strong style={{ fontWeight: 600 }}>{label}:</strong> {value}
    </div>
  );
}

/**
 * The `indexing` chip (#437): a large doc chunked+embedded into the conversation scope this turn.
 * Tier 1: "Index" (amber-olive) + "Indexed {ref} - {chunks} chunks"; Tier 2: chunks + duration
 * (+ optional model, forward-compat) and the error message on failure. Reuses the chip shell.
 */
export function IndexingIO({
  refName,
  chunks,
  ms,
  state,
  model,
  error,
}: {
  refName: string;
  chunks?: number;
  ms?: number | null;
  state: PipelineState;
  model?: string | null;
  error?: string | null;
}): React.ReactElement {
  const label =
    state === "in-progress"
      ? `Indexing ${refName}…`
      : chunks != null
        ? `Indexed ${refName} - ${chunks} chunks`
        : `Indexed ${refName}`;
  return (
    <Chip testid="timeline-indexing" bg="#fbf6e6" hue={INDEXING} category="Index" label={label} state={state}>
      {chunks != null && <Row label="Chunks" value={String(chunks)} />}
      {ms != null && <Row label="Duration" value={fmtMs(ms)} />}
      {model && <Row label="Model" value={model} />}
      {state === "error" && error && (
        <div data-testid="pipelineio-error" style={{ color: ERR, fontSize: "0.78rem", margin: "2px 0", whiteSpace: "pre-wrap" }}>
          {error}
        </div>
      )}
    </Chip>
  );
}

/** A single 3-cell score bar (aria-hidden decoration; the numeric score is the accessible value). */
function ScoreBar({ score }: { score: number }): React.ReactElement {
  // Clamp to [0,1] and quantize to 0..3 filled cells.
  const filled = Math.max(0, Math.min(3, Math.round(Math.max(0, Math.min(1, score)) * 3)));
  return (
    <span aria-hidden style={{ display: "inline-flex", gap: 1, flex: "0 0 auto" }}>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          style={{
            width: 6,
            height: 9,
            borderRadius: 1,
            background: i < filled ? RETRIEVAL : "rgba(21,88,176,0.18)",
          }}
        />
      ))}
    </span>
  );
}

/**
 * The `retrieval` chip (#437): the hybrid query that assembled context. Tier 1: "Retrieval" (indigo)
 * + "Retrieved {hits} passages ({scope})" (or "No passages retrieved ({scope})" when hits===0, pill
 * stays `done` — a 0-hit run is signal, not error). Tier 2: a query/top-k/hits/duration meta header
 * + an ordered `<ol>` citation list ({source, score}), each row a numeric score (accessible) + a
 * decorative 3-cell fill bar + the bolded, ellipsised source.
 */
export function RetrievalIO({
  query,
  topK,
  hits,
  scope,
  ms,
  citations,
  state,
}: {
  query?: string;
  topK?: number;
  hits?: number;
  scope?: "global" | "conversation" | "union";
  ms?: number | null;
  citations?: { source: string; score: number }[];
  state: PipelineState;
}): React.ReactElement {
  const scopeText = scope ?? "global";
  const n = hits ?? 0;
  const label =
    state === "in-progress"
      ? "Retrieving…"
      : n === 0
        ? `No passages retrieved (${scopeText})`
        : `Retrieved ${n} passages (${scopeText})`;
  // Highest score first; the backend caps the list at <=8 (winners-only), so no expander needed.
  const rows = [...(citations ?? [])].sort((a, b) => b.score - a.score);
  return (
    <Chip
      testid="timeline-retrieval"
      bg="#eaf1fb"
      hue={RETRIEVAL}
      category="Retrieval"
      label={label}
      state={state}
      defaultOpen={n > 0}
    >
      {query != null && query !== "" && (
        <div style={{ color: READABLE, fontSize: "0.78rem" }} title={query}>
          <strong style={{ fontWeight: 600 }}>Query:</strong> &quot;{clip(query, 80)}&quot;
        </div>
      )}
      {topK != null && <Row label="Top-k" value={String(topK)} />}
      <Row label="Hits" value={String(n)} />
      {ms != null && <Row label="Duration" value={fmtMs(ms)} />}
      {n === 0 ? (
        <div style={{ color: READABLE, fontSize: "0.78rem", marginTop: 2 }}>No passages matched.</div>
      ) : (
        <ol data-testid="retrieval-citations" style={{ listStyle: "none", margin: "3px 0 0", padding: 0 }}>
          {rows.map((c, i) => (
            <li
              key={`${c.source}-${i}`}
              style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.78rem", padding: "1px 0" }}
            >
              <ScoreBar score={c.score} />
              <span data-testid="retrieval-score" style={{ color: READABLE, fontVariantNumeric: "tabular-nums", flex: "0 0 auto" }}>
                {c.score.toFixed(2)}
              </span>
              <span
                style={{ color: "#1f2937", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                title={c.source}
              >
                {c.source}
              </span>
            </li>
          ))}
        </ol>
      )}
    </Chip>
  );
}

/**
 * The `ner` chip (#437): entity extraction. DORMANT until Phase 6 — it renders only when a `ner`
 * trace item actually exists (the caller gates on the item's presence; no placeholder otherwise).
 * Tier 1: "Entities" (fuchsia-plum) + "Extracted {count} entities"; Tier 2: the per-type breakdown.
 */
export function NerIO({
  count,
  types,
  state,
}: {
  count?: number;
  types?: { type: string; count: number }[];
  state: PipelineState;
}): React.ReactElement {
  const n = count ?? 0;
  const breakdown = (types ?? []).map((t) => `${t.type}: ${t.count}`).join(" - ");
  return (
    <Chip testid="timeline-ner" bg="#f7e9f6" hue={NER} category="Entities" label={`Extracted ${n} entities`} state={state}>
      {breakdown !== "" && <div style={{ color: READABLE, fontSize: "0.78rem" }}>{breakdown}</div>}
    </Chip>
  );
}
