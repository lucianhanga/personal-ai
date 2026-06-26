import { useState } from "react";

import { FolderAddForm } from "./FolderAddForm";
import { FolderSourceCard } from "./FolderSourceCard";
import { useFolderSources } from "./useFolderSources";

const MUTED = "#6b7280";
const AMBER = "#b06f00";

interface FolderSourcesPanelProps {
  token: string;
}

/** Settings > Documents v2 — Folder sources region (#458). Owns the folder list via
 * `useFolderSources`, renders the loading skeleton / empty state / offline notice, the add form
 * (behind an "Add folder source" toggle), and the card list. Mutating actions are disabled while the
 * backend is unreachable. The per-file detail / pipeline views are a later pass. */
export function FolderSourcesPanel({ token }: FolderSourcesPanelProps): React.ReactElement {
  const { folders, loading, offline, addFolder, removeFolder } = useFolderSources(token);
  const [adding, setAdding] = useState(false);

  return (
    <section
      data-testid="folder-sources-panel"
      aria-label="Folder sources"
      style={{ marginTop: "1rem" }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.5rem",
          marginBottom: "0.4rem",
        }}
      >
        <strong style={{ flex: 1, fontSize: "0.9rem" }}>Folder sources</strong>
        <button
          data-testid="folder-sources-add-toggle"
          type="button"
          onClick={() => setAdding((v) => !v)}
          disabled={offline}
          aria-expanded={adding}
          style={{
            padding: "0.3rem 0.7rem",
            border: "1px solid #1a7f37",
            borderRadius: 6,
            background: "none",
            color: offline ? MUTED : "#1a7f37",
            fontSize: "0.8rem",
            fontWeight: 600,
            cursor: offline ? "not-allowed" : "pointer",
          }}
        >
          Add folder source
        </button>
      </div>

      <p style={{ color: MUTED, fontSize: "0.78rem", margin: "0 0 0.5rem" }}>
        Watch an on-disk folder; its files are scanned and embedded for retrieval. Turn on “Use my
        documents” in the chat view to ground answers in them.
      </p>

      {offline && (
        <p
          data-testid="folder-sources-offline"
          role="status"
          aria-live="polite"
          style={{ color: AMBER, fontSize: "0.8rem", margin: "0.25rem 0" }}
        >
          Folder sources are unavailable right now — the backend could not be reached.
        </p>
      )}

      {adding && !offline && (
        <FolderAddForm
          onAdd={addFolder}
          disabled={offline}
          onCancel={() => setAdding(false)}
        />
      )}

      {loading ? (
        <div
          data-testid="folder-sources-loading"
          role="status"
          aria-live="polite"
          aria-busy="true"
          style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}
        >
          <span style={{ position: "absolute", left: -9999 }}>Loading folder sources…</span>
          {[0, 1].map((i) => (
            <div
              key={i}
              aria-hidden="true"
              style={{
                height: "3.5rem",
                borderRadius: 8,
                background:
                  "linear-gradient(90deg, rgba(127,127,127,0.06), rgba(127,127,127,0.12), rgba(127,127,127,0.06))",
              }}
            />
          ))}
        </div>
      ) : offline ? null : folders.length === 0 ? (
        <p
          data-testid="folder-sources-empty"
          style={{ color: MUTED, fontSize: "0.82rem", margin: "0.25rem 0" }}
        >
          No folder sources yet — add a folder to index its files for retrieval.
        </p>
      ) : (
        <ul
          data-testid="folder-sources-list"
          style={{ margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "0.5rem" }}
        >
          {folders.map((f) => (
            <FolderSourceCard key={f.id} folder={f} token={token} onRemove={removeFolder} />
          ))}
        </ul>
      )}
    </section>
  );
}
