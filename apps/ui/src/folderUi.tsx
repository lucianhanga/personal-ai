import type { FolderCounts, FolderFileStatus } from "./api";

// Shared color code for the folder-source UI (#458). Mirrors FolderSourceCard's constants so the
// drill-down reads identically: green synced/idle, amber in-progress, red error, muted neutral.
export const GREEN = "#1a7f37";
export const AMBER = "#b06f00";
export const RED = "#b00020";
export const MUTED = "#6b7280";

// Per-file status -> { word, color }. The word carries the meaning; color only reinforces it
// (never color alone). Same vocabulary as the bucket counts.
export const FILE_STATUS: Record<FolderFileStatus, { word: string; color: string }> = {
  synced: { word: "Synced", color: GREEN },
  indexing: { word: "Indexing", color: AMBER },
  pending: { word: "Pending", color: AMBER },
  stale: { word: "Stale", color: AMBER },
  error: { word: "Error", color: RED },
  deleted: { word: "Deleted", color: MUTED },
};

// Rollup bucket order + per-bucket hue (shared by the card rollup and the detail header). Only
// non-zero buckets render, joined by " · ".
export const ROLLUP_BUCKETS: { key: keyof FolderCounts; label: string; color: string }[] = [
  { key: "synced", label: "synced", color: GREEN },
  { key: "indexing", label: "indexing", color: AMBER },
  { key: "pending", label: "pending", color: AMBER },
  { key: "stale", label: "stale", color: AMBER },
  { key: "error", label: "error", color: RED },
  { key: "deleted", label: "deleted", color: MUTED },
];

/** Human-readable byte size; null/absent -> em dash. */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb < 10 ? kb.toFixed(1) : Math.round(kb)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} MB`;
  return `${(mb / 1024).toFixed(1)} GB`;
}

/** Short local date for an ISO timestamp; null/absent -> em dash. */
export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** A word+color status pill for a single file. */
export function FileStatusPill({ status }: { status: FolderFileStatus }): React.ReactElement {
  const { word, color } = FILE_STATUS[status];
  return (
    <span
      data-testid="file-status"
      data-status={status}
      style={{
        color,
        background: "rgba(127,127,127,0.08)",
        borderRadius: 8,
        padding: "0 0.4rem",
        fontSize: "0.7rem",
        fontWeight: 600,
        flex: "0 0 auto",
      }}
    >
      {word}
    </span>
  );
}

/** A rollup line of non-zero status buckets ("12 synced · 1 error"), word+color per bucket. Used for
 * the detail header (live SSE counts) and per-directory descendant rollups in the tree. */
export function StatusRollup({
  counts,
  testid,
  emptyText = "No files indexed yet",
}: {
  counts: FolderCounts;
  testid?: string;
  emptyText?: string;
}): React.ReactElement {
  const segments = ROLLUP_BUCKETS.map((b) => ({ ...b, n: counts[b.key] ?? 0 })).filter(
    (b) => b.n > 0,
  );
  return (
    <span
      data-testid={testid}
      style={{ fontSize: "0.76rem", display: "inline-flex", flexWrap: "wrap", gap: "0.25rem" }}
    >
      {segments.length === 0 ? (
        <span style={{ color: MUTED }}>{emptyText}</span>
      ) : (
        segments.map((s, i) => (
          <span key={s.key}>
            <span style={{ color: s.color, fontWeight: 600 }}>
              {s.n} {s.label}
            </span>
            {i < segments.length - 1 && <span style={{ color: "#c0c0c0" }}> · </span>}
          </span>
        ))
      )}
    </span>
  );
}
