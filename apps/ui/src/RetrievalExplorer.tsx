import { useState } from "react";

import { retrievePassages, type RetrievedPassage } from "./api";
import { MUTED, RED } from "./folderUi";

// The Retrieval Explorer (#465): a Settings playground that runs standalone hybrid retrieval over the
// GLOBAL corpus and shows the ranked passages it would surface — WITHOUT generating a chat answer.
// Rank is the primary signal; the RRF-fused score is meaningful only relative to its siblings, so it
// renders as a relative bar (never an absolute number), with the numeric value as a text equivalent.

const RETRIEVAL = "#1558b0"; // royal indigo — shared with RetrievalIO/the chat timeline (AA on white)
const READABLE = "#1f2937"; // the passage/provenance text a user must read
const TOP_K_OPTIONS = [4, 8, 12, 20];
const SNIPPET_CHARS = 280; // truncate long passages; an expander reveals the rest

// Visually-hidden but screen-reader-available (mirrors MessageList's sr-only span).
const SR_ONLY: React.CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  overflow: "hidden",
  clip: "rect(0 0 0 0)",
  whiteSpace: "nowrap",
};

type ExplorerState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "done"; passages: RetrievedPassage[]; ms: number | null; query: string };

interface RetrievalExplorerProps {
  token: string;
}

/** Settings > Knowledge > Corpus: the Retrieval Explorer. Type a query, pick top-k, Run -> ranked
 * passages with provenance + a relative score bar. An explicit backend call (click or Enter), NOT
 * keystroke-driven. A 0-hit run is a neutral signal, not an error. */
export function RetrievalExplorer({ token }: RetrievalExplorerProps): React.ReactElement {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(8);
  const [state, setState] = useState<ExplorerState>({ kind: "idle" });

  const loading = state.kind === "loading";

  async function run(): Promise<void> {
    const q = query.trim();
    if (q === "" || loading) return;
    setState({ kind: "loading" });
    try {
      const result = await retrievePassages(token, q, topK);
      setState({ kind: "done", passages: result.passages, ms: result.ms, query: result.query });
    } catch {
      // Keep `query` in state untouched so the user can Retry the same search.
      setState({ kind: "error", message: "Retrieval failed. Check the backend and try again." });
    }
  }

  return (
    <section
      data-testid="retrieval-explorer"
      aria-label="Retrieval explorer"
      style={{
        border: "1px solid #eee",
        borderRadius: 8,
        padding: "0.7rem",
        marginBottom: "0.9rem",
        background: "#fbfbfc",
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: "0.4rem", marginBottom: "0.5rem" }}>
        <span style={{ color: RETRIEVAL, fontWeight: 600, fontSize: "0.85rem" }}>Retrieval explorer</span>
        <span style={{ color: MUTED, fontSize: "0.74rem" }}>global corpus</span>
      </div>
      <p style={{ color: MUTED, fontSize: "0.78rem", margin: "0 0 0.6rem" }}>
        See what the retriever would surface for a query — ranked passages with their source, no chat
        answer. Rank is the primary signal.
      </p>

      <form
        data-testid="retrieval-form"
        onSubmit={(e) => {
          e.preventDefault();
          void run();
        }}
        style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", alignItems: "center" }}
      >
        <label htmlFor="retrieval-query" style={SR_ONLY}>
          Retrieval query
        </label>
        <input
          id="retrieval-query"
          data-testid="retrieval-query"
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search the indexed corpus…"
          disabled={loading}
          style={{
            flex: "1 1 220px",
            minWidth: 160,
            padding: "0.4rem 0.55rem",
            border: "1px solid #ccc",
            borderRadius: 6,
            fontSize: "0.85rem",
          }}
        />
        <label htmlFor="retrieval-topk" style={{ color: MUTED, fontSize: "0.78rem" }}>
          Top-k
        </label>
        <select
          id="retrieval-topk"
          data-testid="retrieval-topk"
          value={topK}
          onChange={(e) => setTopK(Number(e.target.value))}
          disabled={loading}
          style={{ padding: "0.35rem 0.4rem", border: "1px solid #ccc", borderRadius: 6, fontSize: "0.82rem" }}
        >
          {TOP_K_OPTIONS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
        <button
          type="submit"
          data-testid="retrieval-run"
          disabled={loading || query.trim() === ""}
          style={{
            padding: "0.4rem 0.9rem",
            border: "none",
            borderRadius: 6,
            background: loading || query.trim() === "" ? "#9bb6dd" : RETRIEVAL,
            color: "#fff",
            fontSize: "0.85rem",
            fontWeight: 600,
            cursor: loading || query.trim() === "" ? "default" : "pointer",
          }}
        >
          {loading ? "Running…" : "Run"}
        </button>
      </form>

      <div aria-live="polite" aria-busy={loading} style={{ marginTop: "0.6rem" }}>
        {state.kind === "idle" && (
          <p data-testid="retrieval-idle" style={{ color: MUTED, fontSize: "0.8rem", margin: 0 }}>
            Enter a query and run a retrieval to see ranked passages.
          </p>
        )}

        {state.kind === "loading" && (
          <p data-testid="retrieval-loading" role="status" style={{ color: MUTED, fontSize: "0.82rem", margin: 0 }}>
            Running retrieval…
          </p>
        )}

        {state.kind === "error" && (
          <div data-testid="retrieval-error" role="alert" style={{ fontSize: "0.82rem" }}>
            <span style={{ color: RED }}>{state.message}</span>
            <button
              type="button"
              data-testid="retrieval-retry"
              onClick={() => void run()}
              style={{
                marginLeft: "0.5rem",
                padding: "0.2rem 0.6rem",
                border: `1px solid ${RED}`,
                borderRadius: 6,
                background: "none",
                color: RED,
                fontSize: "0.78rem",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Retry
            </button>
          </div>
        )}

        {state.kind === "done" && state.passages.length === 0 && (
          // Empty = neutral signal (searched, found nothing) — muted, NOT the red error path.
          <p data-testid="retrieval-empty" style={{ color: MUTED, fontSize: "0.82rem", margin: 0 }}>
            No passages retrieved for “{state.query}”. Nothing in the corpus matched.
          </p>
        )}

        {state.kind === "done" && state.passages.length > 0 && (
          <Results passages={state.passages} ms={state.ms} />
        )}
      </div>
    </section>
  );
}

/** The ranked-passage list. Scores are normalized against the top passage's score so the bar reads
 * as a RELATIVE strength; the numeric score is exposed as a text equivalent (the bar is aria-hidden). */
function Results({
  passages,
  ms,
}: {
  passages: RetrievedPassage[];
  ms: number | null;
}): React.ReactElement {
  const maxScore = passages.reduce((m, p) => Math.max(m, p.score), 0);
  return (
    <div>
      <div data-testid="retrieval-summary" style={{ color: MUTED, fontSize: "0.76rem", marginBottom: "0.35rem" }}>
        {passages.length} passage{passages.length === 1 ? "" : "s"}
        {ms != null ? ` · ${ms} ms` : ""}
      </div>
      <ol data-testid="retrieval-results" style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {passages.map((p) => (
          <PassageRow key={`${p.source_id}-${p.rank}`} passage={p} maxScore={maxScore} />
        ))}
      </ol>
    </div>
  );
}

function PassageRow({
  passage,
  maxScore,
}: {
  passage: RetrievedPassage;
  maxScore: number;
}): React.ReactElement {
  const [expanded, setExpanded] = useState(false);
  const long = passage.text.length > SNIPPET_CHARS;
  const shown = expanded || !long ? passage.text : `${passage.text.slice(0, SNIPPET_CHARS)}…`;
  const provenance =
    [passage.name ?? passage.source_id, passage.locator].filter((s) => s != null && s !== "").join(" · ");

  return (
    <li
      data-testid="retrieval-passage"
      data-rank={passage.rank}
      style={{
        display: "flex",
        gap: "0.6rem",
        padding: "0.5rem 0",
        borderTop: "1px solid #f0f0f0",
      }}
    >
      <span
        data-testid="retrieval-rank"
        aria-hidden
        style={{
          flex: "0 0 auto",
          minWidth: 24,
          textAlign: "right",
          color: RETRIEVAL,
          fontWeight: 700,
          fontVariantNumeric: "tabular-nums",
          fontSize: "0.85rem",
        }}
      >
        #{passage.rank}
      </span>
      <div style={{ flex: "1 1 auto", minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.2rem" }}>
          <ScoreBar score={passage.score} maxScore={maxScore} rank={passage.rank} />
          <span
            data-testid="retrieval-provenance"
            style={{
              color: MUTED,
              fontSize: "0.74rem",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
            title={provenance}
          >
            {provenance}
          </span>
          <span
            data-testid="retrieval-source-kind"
            style={{
              flex: "0 0 auto",
              color: RETRIEVAL,
              background: "rgba(21,88,176,0.10)",
              borderRadius: 8,
              padding: "0 0.4rem",
              fontSize: "0.68rem",
              fontWeight: 600,
            }}
          >
            {passage.source_kind}
          </span>
        </div>
        <p
          data-testid="retrieval-text"
          style={{ margin: 0, color: READABLE, fontSize: "0.82rem", lineHeight: 1.45, whiteSpace: "pre-wrap" }}
        >
          {shown}
        </p>
        {long && (
          <button
            type="button"
            data-testid="retrieval-expand"
            aria-expanded={expanded}
            onClick={() => setExpanded((e) => !e)}
            style={{
              marginTop: "0.2rem",
              padding: 0,
              border: "none",
              background: "none",
              color: RETRIEVAL,
              fontSize: "0.76rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            {expanded ? "Show less" : "Show more"}
          </button>
        )}
      </div>
    </li>
  );
}

/** A relative score bar: width is the passage's score as a fraction of the top score (so the #1
 * passage fills the bar). The bar is decorative (aria-hidden); a visually-hidden text equivalent
 * carries the rank + numeric score for assistive tech — never color/length alone. */
function ScoreBar({
  score,
  maxScore,
  rank,
}: {
  score: number;
  maxScore: number;
  rank: number;
}): React.ReactElement {
  const fraction = maxScore > 0 ? Math.max(0, Math.min(1, score / maxScore)) : 0;
  return (
    <span style={{ flex: "0 0 auto", display: "inline-flex", alignItems: "center" }}>
      <span
        aria-hidden
        style={{
          display: "inline-block",
          width: 56,
          height: 6,
          borderRadius: 3,
          background: "rgba(21,88,176,0.16)",
          overflow: "hidden",
        }}
      >
        <span
          style={{
            display: "block",
            width: `${Math.round(fraction * 100)}%`,
            height: "100%",
            background: RETRIEVAL,
          }}
        />
      </span>
      <span data-testid="retrieval-score" style={SR_ONLY}>
        Rank {rank}, relevance score {score.toFixed(3)}
      </span>
    </span>
  );
}
