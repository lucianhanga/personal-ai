import { EntityBrowser } from "./EntityBrowser";
import { FolderSourcesPanel } from "./FolderSourcesPanel";
import type { DocumentInfo } from "./api";

interface DocumentsPanelProps {
  token: string;
  files: DocumentInfo[];
  uploading: boolean;
  onUpload: (file: File | undefined) => void;
  onDelete: (id: string) => void;
}

/** Settings > Documents: three labelled regions — "Individual uploads" (the existing per-file upload
 * + ingested list, unchanged), "Folder sources" (watch an on-disk folder, #458), and "Entities" (the
 * corpus-global knowledge-graph browser, #451). */
export function DocumentsPanel({
  token,
  files,
  uploading,
  onUpload,
  onDelete,
}: DocumentsPanelProps): React.ReactElement {
  return (
    <section
      data-testid="documents-panel"
      aria-label="documents"
      style={{ border: "1px solid #ddd", borderRadius: 8, padding: "0.75rem" }}
    >
      {/* Region 1: individual uploads (existing UI, behavior unchanged). */}
      <section data-testid="individual-uploads" aria-label="Individual uploads">
        <div
          style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}
        >
          <strong style={{ flex: 1 }}>Individual uploads</strong>
          {uploading && <span data-testid="upload-status">uploading…</span>}
        </div>
        <label style={{ fontSize: "0.85rem" }}>
          Upload:{" "}
          <input
            data-testid="file-input"
            type="file"
            accept=".txt,.md,.markdown,.pdf,.docx"
            disabled={uploading}
            onChange={(e) => onUpload(e.target.files?.[0])}
          />
        </label>
        <p style={{ color: "#888", fontSize: "0.75rem", margin: "0.35rem 0" }}>
          Uploaded documents are embedded for retrieval. Turn on “Use my documents” in the chat view
          to ground answers in them.
        </p>
        {files.length === 0 ? (
          <p data-testid="documents-empty" style={{ color: "#888", fontSize: "0.82rem" }}>
            No documents uploaded yet.
          </p>
        ) : (
          <ul
            data-testid="file-list"
            style={{ margin: 0, paddingLeft: "1rem", fontSize: "0.82rem" }}
          >
            {files.map((f) => (
              <li key={f.id} data-testid="file-item" style={{ padding: "0.15rem 0" }}>
                {f.name} <span style={{ color: "#888" }}>({f.chunk_count} chunks)</span>{" "}
                <button
                  data-testid={`delete-${f.id}`}
                  onClick={() => onDelete(f.id)}
                  style={{ fontSize: "0.75rem" }}
                >
                  remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <hr style={{ border: "none", borderTop: "1px solid #eee", margin: "0.75rem 0 0" }} />

      {/* Region 2: folder sources (#458). Self-fetches via useFolderSources(token). */}
      <FolderSourcesPanel token={token} />

      <hr style={{ border: "none", borderTop: "1px solid #eee", margin: "0.75rem 0 0" }} />

      {/* Region 3: corpus-global entity browser (#451). Self-fetches via the entities API. */}
      <EntityBrowser token={token} />
    </section>
  );
}
