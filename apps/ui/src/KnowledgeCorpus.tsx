import { useEffect, useRef, useState } from "react";

import {
  fetchDocumentChunks,
  fetchEntities,
  fetchFiles,
  type DocumentChunk,
  type DocumentInfo,
} from "./api";
import { MUTED, RED, formatWhen } from "./folderUi";
import { STATUS_OK, STATUS_WARN } from "./knowledgeUi";
import { RetrievalExplorer } from "./RetrievalExplorer";

interface KnowledgeCorpusTabProps {
  token: string;
  // The document whose chunks the inspector shows (null = closed). Lifted into KnowledgePanel so the
  // Graph tab's "Open in Corpus" deep link and the corpus table both drive the same inspector.
  selectedDocId: string | null;
  onSelectDocument: (id: string | null) => void;
}

interface CorpusData {
  files: DocumentInfo[];
  entityCount: number;
}

/** Knowledge > Corpus (P0 overview): stat cards (documents, total chunks, entities) + a per-document
 * table with an indexed/not-indexed flag + a chunk inspector. Derived from the files + entities APIs;
 * selecting a document row (or deep-linking from the Graph tab) opens its chunks. */
export function KnowledgeCorpusTab({
  token,
  selectedDocId,
  onSelectDocument,
}: KnowledgeCorpusTabProps): React.ReactElement {
  const [data, setData] = useState<CorpusData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    Promise.all([
      fetchFiles(token, { includeSynced: true }),
      fetchEntities(token, { limit: 1000 }),
    ])
      .then(([files, entities]) => {
        if (active) setData({ files, entityCount: entities.length });
      })
      .catch(() => active && setError("Could not load the corpus."))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [token]);

  // The selected document's name for the inspector header — resolved from the loaded corpus, falling
  // back to the id (e.g. a deep link that arrives before the file list finishes loading).
  const selectedName =
    (selectedDocId && data?.files.find((f) => f.id === selectedDocId)?.name) || selectedDocId || "";

  return (
    <section data-testid="knowledge-corpus-tab" aria-label="Corpus overview">
      <p style={{ color: MUTED, fontSize: "0.82rem", margin: "0 0 0.6rem" }}>
        What is indexed for retrieval: your documents, their chunks, and the entities extracted from
        them.
      </p>

      <RetrievalExplorer token={token} />

      {selectedDocId && (
        <ChunkInspector
          token={token}
          docId={selectedDocId}
          docName={selectedName}
          onClose={() => onSelectDocument(null)}
        />
      )}

      <div aria-live="polite" aria-busy={loading}>
        {loading ? (
          <p data-testid="corpus-loading" role="status" style={{ color: MUTED, fontSize: "0.85rem" }}>
            Loading corpus…
          </p>
        ) : error ? (
          <p data-testid="corpus-error" role="alert" style={{ color: RED, fontSize: "0.85rem" }}>
            {error}
          </p>
        ) : data && data.files.length === 0 ? (
          <p data-testid="corpus-empty" style={{ color: MUTED, fontSize: "0.85rem" }}>
            No documents yet — upload or add a folder source to build your corpus.
          </p>
        ) : data ? (
          <CorpusOverview
            files={data.files}
            entityCount={data.entityCount}
            selectedDocId={selectedDocId}
            onSelectDocument={onSelectDocument}
          />
        ) : null}
      </div>
    </section>
  );
}

function StatCard({
  testid,
  label,
  value,
}: {
  testid: string;
  label: string;
  value: number;
}): React.ReactElement {
  return (
    <div
      data-testid={testid}
      style={{
        flex: "1 1 110px",
        minWidth: 100,
        border: "1px solid #eee",
        borderRadius: 8,
        padding: "0.55rem 0.7rem",
        background: "#fbfbfc",
      }}
    >
      <div style={{ fontSize: "1.35rem", fontWeight: 700, color: "#222" }}>{value}</div>
      <div style={{ fontSize: "0.74rem", color: MUTED }}>{label}</div>
    </div>
  );
}

function CorpusOverview({
  files,
  entityCount,
  selectedDocId,
  onSelectDocument,
}: {
  files: DocumentInfo[];
  entityCount: number;
  selectedDocId: string | null;
  onSelectDocument: (id: string | null) => void;
}): React.ReactElement {
  const totalChunks = files.reduce((sum, f) => sum + (f.chunk_count ?? 0), 0);

  return (
    <div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.75rem" }}>
        <StatCard testid="corpus-stat-documents" label="Documents" value={files.length} />
        <StatCard testid="corpus-stat-chunks" label="Total chunks" value={totalChunks} />
        <StatCard testid="corpus-stat-entities" label="Entities" value={entityCount} />
      </div>

      <table
        data-testid="corpus-table"
        style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}
      >
        <thead>
          <tr style={{ textAlign: "left", color: MUTED, borderBottom: "1px solid #eee" }}>
            <th style={{ padding: "0.3rem 0.4rem", fontWeight: 600 }}>Document</th>
            <th style={{ padding: "0.3rem 0.4rem", fontWeight: 600 }}>Chunks</th>
            <th style={{ padding: "0.3rem 0.4rem", fontWeight: 600 }}>Status</th>
            <th style={{ padding: "0.3rem 0.4rem", fontWeight: 600 }}>Added</th>
          </tr>
        </thead>
        <tbody>
          {files.map((f) => {
            const indexed = (f.chunk_count ?? 0) > 0;
            const active = selectedDocId === f.id;
            return (
              <tr
                key={f.id}
                data-testid="corpus-row"
                data-doc-id={f.id}
                style={{ borderBottom: "1px solid #f2f2f2", background: active ? "rgba(51,65,85,0.06)" : undefined }}
              >
                <td style={{ padding: "0.3rem 0.4rem" }}>
                  {/* The name cell is a button so the chunk inspector is keyboard-reachable; a button
                      can't wrap a <tr>, so it lives in the first cell and toggles the selection. */}
                  <button
                    data-testid="corpus-row-button"
                    data-doc-id={f.id}
                    type="button"
                    aria-pressed={active}
                    aria-expanded={active}
                    onClick={() => onSelectDocument(active ? null : f.id)}
                    style={{
                      border: "none",
                      background: "none",
                      padding: 0,
                      textAlign: "left",
                      color: active ? "#0b3a66" : "#1a6fb0",
                      fontWeight: active ? 600 : 400,
                      fontSize: "0.8rem",
                      cursor: "pointer",
                      textDecoration: "underline",
                    }}
                  >
                    {f.name}
                  </button>
                </td>
                <td style={{ padding: "0.3rem 0.4rem", color: "#444" }}>{f.chunk_count ?? 0}</td>
                <td style={{ padding: "0.3rem 0.4rem" }}>
                  <span
                    data-testid="corpus-status"
                    data-indexed={indexed}
                    style={{
                      color: indexed ? STATUS_OK : STATUS_WARN,
                      fontWeight: 600,
                      fontSize: "0.74rem",
                    }}
                  >
                    {indexed ? "Indexed" : "Not indexed"}
                  </span>
                </td>
                <td style={{ padding: "0.3rem 0.4rem", color: MUTED }}>{formatWhen(f.created_at)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Chunk inspector (#KAG): the indexed chunks of one document (index + text), with the standard
 * loading/empty/error trio. Collapsible — the close button clears the lifted selection. Fetches
 * fresh whenever the document changes; a request guard discards a stale response. */
function ChunkInspector({
  token,
  docId,
  docName,
  onClose,
}: {
  token: string;
  docId: string;
  docName: string;
  onClose: () => void;
}): React.ReactElement {
  const [chunks, setChunks] = useState<DocumentChunk[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reqRef = useRef(0);

  useEffect(() => {
    const req = ++reqRef.current;
    setLoading(true);
    setError(null);
    setChunks(null);
    fetchDocumentChunks(token, docId)
      .then((cs) => {
        if (reqRef.current === req) setChunks(cs);
      })
      .catch(() => {
        if (reqRef.current === req) setError("Could not load the document's chunks.");
      })
      .finally(() => {
        if (reqRef.current === req) setLoading(false);
      });
  }, [token, docId]);

  return (
    <section
      data-testid="chunk-inspector"
      role="region"
      aria-label={`Chunks for ${docName}`}
      style={{
        border: "1px solid #eee",
        borderLeft: "3px solid #334155",
        borderRadius: 6,
        padding: "0.5rem 0.6rem",
        margin: "0 0 0.75rem",
        background: "#fbfbfc",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.5rem" }}>
        <strong style={{ fontSize: "0.85rem", color: "#222" }}>
          Chunks · {docName}
          {chunks ? <span style={{ color: MUTED, fontWeight: 400 }}> ({chunks.length})</span> : null}
        </strong>
        <button
          data-testid="chunk-inspector-close"
          type="button"
          onClick={onClose}
          aria-label="Close chunk inspector"
          style={{
            border: "1px solid #ddd",
            borderRadius: 5,
            background: "none",
            color: "#555",
            fontSize: "0.72rem",
            padding: "0.1rem 0.45rem",
            cursor: "pointer",
            flex: "0 0 auto",
          }}
        >
          Close
        </button>
      </div>

      <div aria-live="polite" aria-busy={loading} style={{ marginTop: "0.4rem" }}>
        {loading ? (
          <p data-testid="chunk-loading" role="status" style={{ color: MUTED, fontSize: "0.8rem", margin: 0 }}>
            Loading chunks…
          </p>
        ) : error ? (
          <p data-testid="chunk-error" role="alert" style={{ color: RED, fontSize: "0.8rem", margin: 0 }}>
            {error}
          </p>
        ) : chunks && chunks.length === 0 ? (
          <p data-testid="chunk-empty" style={{ color: MUTED, fontSize: "0.8rem", margin: 0 }}>
            This document has no indexed chunks yet.
          </p>
        ) : chunks ? (
          <ol data-testid="chunk-list" style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: "0.4rem" }}>
            {chunks.map((c) => (
              <li
                key={c.index}
                data-testid="chunk-row"
                data-chunk-index={c.index}
                style={{ border: "1px solid #f0f0f0", borderRadius: 5, padding: "0.35rem 0.45rem", background: "#fff" }}
              >
                <div style={{ fontSize: "0.68rem", fontWeight: 600, color: MUTED, marginBottom: "0.15rem" }}>
                  Chunk {c.index}
                </div>
                <div style={{ fontSize: "0.78rem", color: "#333", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                  {c.text}
                </div>
              </li>
            ))}
          </ol>
        ) : null}
      </div>
    </section>
  );
}
