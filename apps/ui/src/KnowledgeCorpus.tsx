import { useEffect, useState } from "react";

import { fetchEntities, fetchFiles, type DocumentInfo } from "./api";
import { MUTED, RED, formatWhen } from "./folderUi";
import { STATUS_OK, STATUS_WARN } from "./knowledgeUi";
import { RetrievalExplorer } from "./RetrievalExplorer";

interface KnowledgeCorpusTabProps {
  token: string;
}

interface CorpusData {
  files: DocumentInfo[];
  entityCount: number;
}

/** Knowledge > Corpus (P0 overview): stat cards (documents, total chunks, entities) + a per-document
 * table with an indexed/not-indexed flag. Derived from the files + entities APIs. */
export function KnowledgeCorpusTab({ token }: KnowledgeCorpusTabProps): React.ReactElement {
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

  return (
    <section data-testid="knowledge-corpus-tab" aria-label="Corpus overview">
      <p style={{ color: MUTED, fontSize: "0.82rem", margin: "0 0 0.6rem" }}>
        What is indexed for retrieval: your documents, their chunks, and the entities extracted from
        them.
      </p>

      <RetrievalExplorer token={token} />

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
          <CorpusOverview files={data.files} entityCount={data.entityCount} />
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
}: {
  files: DocumentInfo[];
  entityCount: number;
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
            return (
              <tr key={f.id} data-testid="corpus-row" data-doc-id={f.id} style={{ borderBottom: "1px solid #f2f2f2" }}>
                <td style={{ padding: "0.3rem 0.4rem", color: "#222" }}>{f.name}</td>
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
