import { useEffect, useRef, useState } from "react";

import {
  fetchFolderDetail,
  type FolderCounts,
  type FolderFileOut,
  type FolderFileStatus,
  type FolderSource,
} from "./api";
import { FolderFileTree } from "./FolderFileTree";
import { MUTED, RED, StatusRollup } from "./folderUi";

const PAGE_LIMIT = 200;

// The interactive status filter narrows the LOADED files client-side (so it composes with the name
// search without extra round-trips); "Load more" keeps fetching raw keyset pages. The server-side
// `status=` param is still available on fetchFolderDetail for non-interactive callers.
type FilterKey = "all" | "indexing" | "errors" | "stale" | "synced";
const FILTERS: { key: FilterKey; label: string; status?: FolderFileStatus }[] = [
  { key: "all", label: "All" },
  { key: "indexing", label: "Indexing", status: "indexing" },
  { key: "errors", label: "Errors", status: "error" },
  { key: "stale", label: "Stale", status: "stale" },
  { key: "synced", label: "Synced", status: "synced" },
];

interface FolderDetailProps {
  folder: FolderSource;
  token: string;
  // The card's live (SSE-driven) counts, so the detail header stays in sync with the scan.
  liveCounts: FolderCounts;
}

/** The per-folder drill-down (#458 pass 2), shown when a card is expanded: Files (a collapsible
 * directory tree with a status filter, debounced name search, and keyset "Load more") and Entities
 * (a labelled P3 placeholder). The Files header rollup reflects the card's live SSE counts. */
export function FolderDetail({ folder, token, liveCounts }: FolderDetailProps): React.ReactElement {
  const [tab, setTab] = useState<"files" | "entities">("files");
  const [files, setFiles] = useState<FolderFileOut[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [filter, setFilter] = useState<FilterKey>("all");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const defaultedFilter = useRef(false);

  // Lazy-fetch the first page on mount (the parent mounts this only on first expand).
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    fetchFolderDetail(token, folder.id, { limit: PAGE_LIMIT })
      .then((detail) => {
        if (!active) return;
        setFiles(detail.files);
        setTotal(detail.total);
        setHasMore(
          detail.total != null ? detail.files.length < detail.total : detail.files.length === PAGE_LIMIT,
        );
        // Default the filter to Errors when any file errored, so problems are surfaced first.
        if (!defaultedFilter.current && detail.files.some((f) => f.status === "error")) {
          setFilter("errors");
        }
        defaultedFilter.current = true;
      })
      .catch(() => active && setError("Could not load this folder's files."))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [token, folder.id]);

  // Debounce the name search (250ms) so typing doesn't re-narrow on every keystroke.
  useEffect(() => {
    const t = window.setTimeout(() => setSearch(searchInput), 250);
    return () => window.clearTimeout(t);
  }, [searchInput]);

  async function loadMore(): Promise<void> {
    const after = files[files.length - 1]?.rel_path;
    if (!after) return;
    setLoadingMore(true);
    setError(null);
    try {
      const detail = await fetchFolderDetail(token, folder.id, { after, limit: PAGE_LIMIT });
      const seen = new Set(files.map((f) => f.rel_path));
      const merged = [...files, ...detail.files.filter((f) => !seen.has(f.rel_path))];
      setFiles(merged);
      setTotal(detail.total);
      setHasMore(detail.total != null ? merged.length < detail.total : detail.files.length === PAGE_LIMIT);
    } catch {
      setError("Could not load more files.");
    } finally {
      setLoadingMore(false);
    }
  }

  const activeStatus = FILTERS.find((f) => f.key === filter)?.status;
  const query = search.trim().toLowerCase();
  const narrowed = files.filter((f) => {
    if (activeStatus && f.status !== activeStatus) return false;
    if (query && !f.rel_path.toLowerCase().includes(query)) return false;
    return true;
  });
  const narrowing = filter !== "all" || query !== "";

  const tabStyle = (active: boolean): React.CSSProperties => ({
    padding: "0.35rem 0.7rem",
    border: "none",
    borderBottom: active ? "2px solid #1a7f37" : "2px solid transparent",
    background: "none",
    cursor: "pointer",
    fontSize: "0.84rem",
    fontWeight: active ? 600 : 400,
    color: active ? "#1a7f37" : "#333",
  });

  return (
    <section
      data-testid="folder-detail"
      style={{ marginTop: "0.5rem", borderTop: "1px solid #eee", paddingTop: "0.5rem" }}
    >
      {/* Header: the live SSE rollup (kept in sync with the card). */}
      <div
        data-testid="folder-detail-header"
        aria-live="polite"
        style={{ marginBottom: "0.4rem" }}
      >
        <StatusRollup counts={liveCounts} testid="folder-detail-rollup" />
      </div>

      {/* Tabs (tablist a11y pattern, mirroring SettingsView). */}
      <div role="tablist" aria-label="Folder detail" style={{ display: "flex", gap: "0.25rem", borderBottom: "1px solid #eee" }}>
        <button
          data-testid="folder-detail-tab-files"
          role="tab"
          aria-selected={tab === "files"}
          onClick={() => setTab("files")}
          style={tabStyle(tab === "files")}
        >
          Files
        </button>
        <button
          data-testid="folder-detail-tab-entities"
          role="tab"
          aria-selected={tab === "entities"}
          onClick={() => setTab("entities")}
          style={tabStyle(tab === "entities")}
        >
          Entities
        </button>
      </div>

      {tab === "files" ? (
        <div role="tabpanel" data-testid="folder-detail-files" style={{ paddingTop: "0.5rem" }}>
          {/* Status filter chips. */}
          <div role="group" aria-label="Filter by status" style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem", marginBottom: "0.4rem" }}>
            {FILTERS.map((f) => {
              const active = filter === f.key;
              return (
                <button
                  key={f.key}
                  data-testid={`filter-${f.key}`}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setFilter(f.key)}
                  style={{
                    padding: "0.2rem 0.55rem",
                    borderRadius: 12,
                    border: `1px solid ${active ? "#1a7f37" : "#ddd"}`,
                    background: active ? "rgba(26,127,55,0.1)" : "none",
                    color: active ? "#1a7f37" : "#444",
                    fontSize: "0.76rem",
                    fontWeight: active ? 600 : 400,
                    cursor: "pointer",
                  }}
                >
                  {f.label}
                </button>
              );
            })}
          </div>

          {/* Debounced name search. */}
          <input
            data-testid="folder-file-search"
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search file name…"
            aria-label="Search files by name"
            style={{
              width: "100%",
              boxSizing: "border-box",
              padding: "0.3rem 0.5rem",
              border: "1px solid #ddd",
              borderRadius: 6,
              fontSize: "0.82rem",
              marginBottom: "0.4rem",
            }}
          />

          {/* Loaded-vs-total count (never assume the whole folder is loaded). */}
          <p data-testid="folder-detail-count" style={{ color: MUTED, fontSize: "0.74rem", margin: "0 0 0.4rem" }}>
            Showing {narrowed.length} of {files.length} loaded
            {total != null && total > files.length ? ` (${total} total)` : ""}
          </p>

          {loading ? (
            <p data-testid="folder-detail-loading" role="status" aria-busy="true" style={{ color: MUTED, fontSize: "0.82rem" }}>
              Loading files…
            </p>
          ) : error ? (
            <p data-testid="folder-detail-error" role="alert" style={{ color: RED, fontSize: "0.82rem" }}>
              {error}
            </p>
          ) : (
            <>
              <FolderFileTree files={narrowed} expandAll={narrowing} />
              {error && (
                <p data-testid="folder-detail-error" role="alert" style={{ color: RED, fontSize: "0.8rem" }}>
                  {error}
                </p>
              )}
              {hasMore && (
                <button
                  data-testid="folder-load-more"
                  type="button"
                  onClick={() => void loadMore()}
                  disabled={loadingMore}
                  style={{
                    marginTop: "0.5rem",
                    padding: "0.3rem 0.8rem",
                    border: "1px solid #ddd",
                    borderRadius: 6,
                    background: "none",
                    fontSize: "0.78rem",
                    cursor: loadingMore ? "not-allowed" : "pointer",
                  }}
                >
                  {loadingMore ? "Loading…" : "Load more"}
                </button>
              )}
            </>
          )}
        </div>
      ) : (
        <div role="tabpanel" data-testid="folder-detail-entities" style={{ paddingTop: "0.5rem" }}>
          <p data-testid="folder-entities-empty" style={{ color: MUTED, fontSize: "0.82rem" }}>
            Entities will appear once knowledge-graph extraction lands.
          </p>
        </div>
      )}
    </section>
  );
}
