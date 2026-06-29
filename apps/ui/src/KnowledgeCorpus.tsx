import { useEffect, useMemo, useRef, useState } from "react";

import {
  fetchDocumentChunks,
  fetchEntityStats,
  fetchFiles,
  type DocumentChunk,
  type DocumentInfo,
  type EntityStats,
  type EntityType,
} from "./api";
import { MUTED, RED, formatBytes, formatWhen } from "./folderUi";
import { STATUS_OK, STATUS_WARN, TYPE_META, TYPE_ORDER, TypeBadge } from "./knowledgeUi";
import { RetrievalExplorer } from "./RetrievalExplorer";

// --- pure helpers (exported for unit tests) ---------------------------------------------------

export type DocSortKey = "name" | "size" | "chunks" | "added";
export type DocStatusFilter = "all" | "indexed" | "unindexed";

/** A short human label for a document's MIME type, e.g. "application/pdf" -> "PDF". Falls back to the
 * file extension, then "File". Pure so the mapping is unit-testable. */
export function mimeLabel(mime: string | null | undefined, name = ""): string {
  const m = (mime ?? "").toLowerCase();
  if (m.includes("pdf")) return "PDF";
  if (m.includes("markdown")) return "Markdown";
  if (m.startsWith("text/")) return "Text";
  if (m.startsWith("image/")) return "Image";
  if (m.includes("html")) return "HTML";
  if (m.includes("json")) return "JSON";
  if (m.includes("csv")) return "CSV";
  if (m.includes("word") || m.includes("officedocument")) return "Doc";
  const ext = name.includes(".") ? name.split(".").pop()!.toUpperCase() : "";
  return ext || "File";
}

/** Sort + filter the corpus rows by name search, indexed status, and a sort column/direction. Pure
 * (no DOM) so the table logic is unit-testable. Indexed = chunk_count > 0. */
export function sortFilterDocs(
  files: DocumentInfo[],
  opts: { sort: DocSortKey; dir: "asc" | "desc"; q: string; status: DocStatusFilter },
): DocumentInfo[] {
  const q = opts.q.trim().toLowerCase();
  const filtered = files.filter((f) => {
    if (q && !f.name.toLowerCase().includes(q)) return false;
    const indexed = (f.chunk_count ?? 0) > 0;
    if (opts.status === "indexed" && !indexed) return false;
    if (opts.status === "unindexed" && indexed) return false;
    return true;
  });
  const sign = opts.dir === "asc" ? 1 : -1;
  return [...filtered].sort((a, b) => {
    let cmp = 0;
    if (opts.sort === "name") cmp = a.name.localeCompare(b.name);
    else if (opts.sort === "size") cmp = (a.size_bytes ?? 0) - (b.size_bytes ?? 0);
    else if (opts.sort === "chunks") cmp = (a.chunk_count ?? 0) - (b.chunk_count ?? 0);
    else cmp = (a.created_at ?? "").localeCompare(b.created_at ?? "");
    if (cmp !== 0) return cmp * sign;
    return a.name.localeCompare(b.name); // stable tie-break, always ascending by name
  });
}

interface KnowledgeCorpusTabProps {
  token: string;
  // The document whose chunks the inspector shows (null = closed). Lifted into KnowledgePanel so the
  // Graph tab's "Open in Corpus" deep link and the corpus table both drive the same inspector.
  selectedDocId: string | null;
  onSelectDocument: (id: string | null) => void;
}

interface CorpusData {
  files: DocumentInfo[];
  stats: EntityStats;
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
    Promise.all([fetchFiles(token, { includeSynced: true }), fetchEntityStats(token)])
      .then(([files, stats]) => {
        if (active) setData({ files, stats });
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
            stats={data.stats}
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
  sub,
}: {
  testid: string;
  label: string;
  value: number | string;
  sub?: React.ReactNode;
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
      {sub}
    </div>
  );
}

/** Corpus-wide entity-type breakdown (C-D): a compact bar per type, derived client-side from the
 * entity sample. Color reinforces the type but the count + label carry the meaning. */
function TypeBreakdown({ stats }: { stats: EntityStats }): React.ReactElement | null {
  const counts = stats.by_type;
  const rows = TYPE_ORDER.filter((t) => (counts[t] ?? 0) > 0);
  if (rows.length === 0) return null;
  const max = Math.max(...rows.map((t) => counts[t]!));
  return (
    <div data-testid="corpus-type-breakdown" style={{ margin: "0 0 0.85rem" }}>
      <div style={{ fontSize: "0.74rem", fontWeight: 600, color: MUTED, marginBottom: "0.3rem" }}>
        Entity types
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: "0.2rem" }}>
        {rows.map((t) => (
          <div
            key={t}
            data-testid="corpus-type-row"
            data-type={t}
            style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.76rem" }}
          >
            <TypeBadge type={t as EntityType} />
            <span style={{ width: 92, color: "#444" }}>{TYPE_META[t as EntityType].label}</span>
            <span
              aria-hidden
              style={{
                height: 8,
                width: `${Math.max(4, (counts[t]! / max) * 160)}px`,
                background: TYPE_META[t as EntityType].hue,
                borderRadius: 3,
                flex: "0 0 auto",
              }}
            />
            <span style={{ color: MUTED }}>{counts[t]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const SORT_COLS: { key: DocSortKey; label: string }[] = [
  { key: "name", label: "Document" },
  { key: "size", label: "Size" },
  { key: "chunks", label: "Chunks" },
  { key: "added", label: "Added" },
];
const STATUS_FILTERS: { key: DocStatusFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "indexed", label: "Indexed" },
  { key: "unindexed", label: "Not indexed" },
];

function CorpusOverview({
  files,
  stats,
  selectedDocId,
  onSelectDocument,
}: {
  files: DocumentInfo[];
  stats: EntityStats;
  selectedDocId: string | null;
  onSelectDocument: (id: string | null) => void;
}): React.ReactElement {
  const [sort, setSort] = useState<DocSortKey>("added");
  const [dir, setDir] = useState<"asc" | "desc">("desc");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<DocStatusFilter>("all");

  const totalChunks = files.reduce((sum, f) => sum + (f.chunk_count ?? 0), 0);
  const unindexed = files.filter((f) => (f.chunk_count ?? 0) === 0).length;
  const totalBytes = files.reduce((sum, f) => sum + (f.size_bytes ?? 0), 0);

  const rows = useMemo(
    () => sortFilterDocs(files, { sort, dir, q, status }),
    [files, sort, dir, q, status],
  );

  function toggleSort(key: DocSortKey): void {
    if (key === sort) setDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSort(key);
      setDir(key === "name" ? "asc" : "desc");
    }
  }

  return (
    <div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.75rem" }}>
        <StatCard
          testid="corpus-stat-documents"
          label="Documents"
          value={files.length}
          sub={
            unindexed > 0 ? (
              <div
                data-testid="corpus-stat-unindexed"
                style={{ fontSize: "0.7rem", color: STATUS_WARN, fontWeight: 600 }}
              >
                {unindexed} not indexed
              </div>
            ) : null
          }
        />
        <StatCard testid="corpus-stat-chunks" label="Total chunks" value={totalChunks} />
        <StatCard testid="corpus-stat-entities" label="Entities" value={stats.total} />
        <StatCard testid="corpus-stat-size" label="Corpus size" value={formatBytes(totalBytes)} />
      </div>

      <TypeBreakdown stats={stats} />

      {/* Controls: name search + indexed-status filter (C-B). */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.5rem",
          alignItems: "center",
          marginBottom: "0.5rem",
        }}
      >
        <input
          data-testid="corpus-search"
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search documents…"
          aria-label="Search documents by name"
          style={{
            flex: "1 1 180px",
            border: "1px solid #ddd",
            borderRadius: 5,
            padding: "0.22rem 0.45rem",
            fontSize: "0.78rem",
          }}
        />
        <div role="group" aria-label="Filter by index status" style={{ display: "flex", gap: "0.25rem" }}>
          {STATUS_FILTERS.map((s) => (
            <button
              key={s.key}
              data-testid={`corpus-filter-${s.key}`}
              type="button"
              aria-pressed={status === s.key}
              onClick={() => setStatus(s.key)}
              style={{
                border: "1px solid #ddd",
                borderRadius: 5,
                background: status === s.key ? "rgba(51,65,85,0.08)" : "none",
                color: "#555",
                fontSize: "0.74rem",
                fontWeight: status === s.key ? 600 : 400,
                padding: "0.16rem 0.5rem",
                cursor: "pointer",
              }}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {rows.length === 0 ? (
        <p data-testid="corpus-no-match" style={{ color: MUTED, fontSize: "0.82rem" }}>
          No documents match your search or filter.
        </p>
      ) : (
        <table
          data-testid="corpus-table"
          style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}
        >
          <thead>
            <tr style={{ textAlign: "left", color: MUTED, borderBottom: "1px solid #eee" }}>
              {SORT_COLS.map((col) => {
                const activeSort = sort === col.key;
                return (
                  <th
                    key={col.key}
                    aria-sort={activeSort ? (dir === "asc" ? "ascending" : "descending") : "none"}
                    style={{ padding: "0.3rem 0.4rem", fontWeight: 600 }}
                  >
                    <button
                      data-testid={`corpus-sort-${col.key}`}
                      type="button"
                      onClick={() => toggleSort(col.key)}
                      style={{
                        border: "none",
                        background: "none",
                        padding: 0,
                        font: "inherit",
                        color: activeSort ? "#0b3a66" : MUTED,
                        fontWeight: 600,
                        cursor: "pointer",
                      }}
                    >
                      {col.label}
                      {activeSort ? (dir === "asc" ? " ▲" : " ▼") : ""}
                    </button>
                  </th>
                );
              })}
              <th style={{ padding: "0.3rem 0.4rem", fontWeight: 600 }}>Entities</th>
              <th style={{ padding: "0.3rem 0.4rem", fontWeight: 600 }}>Type</th>
              <th style={{ padding: "0.3rem 0.4rem", fontWeight: 600 }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((f) => {
              const indexed = (f.chunk_count ?? 0) > 0;
              const active = selectedDocId === f.id;
              return (
                <tr
                  key={f.id}
                  data-testid="corpus-row"
                  data-doc-id={f.id}
                  style={{
                    borderBottom: "1px solid #f2f2f2",
                    background: active ? "rgba(51,65,85,0.06)" : undefined,
                  }}
                >
                  <td style={{ padding: "0.3rem 0.4rem", maxWidth: 220 }}>
                    {/* The name cell is a button so the chunk inspector is keyboard-reachable; a
                        button can't wrap a <tr>, so it lives in the first cell and toggles selection. */}
                    <button
                      data-testid="corpus-row-button"
                      data-doc-id={f.id}
                      type="button"
                      aria-pressed={active}
                      aria-expanded={active}
                      title={f.name}
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
                        maxWidth: "100%",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        display: "inline-block",
                      }}
                    >
                      {f.name}
                    </button>
                  </td>
                  <td data-testid="corpus-col-size" style={{ padding: "0.3rem 0.4rem", color: "#444" }}>
                    {f.size_bytes ? formatBytes(f.size_bytes) : "—"}
                  </td>
                  <td style={{ padding: "0.3rem 0.4rem", color: "#444" }}>{f.chunk_count ?? 0}</td>
                  <td style={{ padding: "0.3rem 0.4rem", color: MUTED }}>{formatWhen(f.created_at)}</td>
                  <td
                    data-testid="corpus-col-entities"
                    style={{ padding: "0.3rem 0.4rem", color: "#444" }}
                  >
                    {f.entity_count ?? 0}
                  </td>
                  <td data-testid="corpus-col-type" style={{ padding: "0.3rem 0.4rem", color: "#444" }}>
                    {mimeLabel(f.mime, f.name)}
                  </td>
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
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
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
