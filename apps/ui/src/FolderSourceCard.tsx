import { useEffect, useState } from "react";

import {
  pauseFolder,
  resumeFolder,
  resyncFolder,
  streamFolderEvents,
  type FolderCounts,
  type FolderSource,
  type FolderStatus,
} from "./api";
import { FolderDetail } from "./FolderDetail";
import { RemoveFolderDialog } from "./RemoveFolderDialog";

// Color code (project convention + #458 rule): green idle/synced, amber scanning/in-progress, red
// error, muted paused/neutral. Status is ALWAYS word + color, never color alone.
const GREEN = "#1a7f37";
const AMBER = "#b06f00";
const RED = "#b00020";
const MUTED = "#6b7280";

// Scan-status -> { word, color }. The word carries the meaning; the color reinforces it.
const STATUS_PILL: Record<FolderStatus, { word: string; color: string; bg: string }> = {
  idle: { word: "Idle", color: GREEN, bg: "rgba(26,127,55,0.12)" },
  scanning: { word: "Scanning", color: AMBER, bg: "rgba(176,111,0,0.12)" },
  error: { word: "Error", color: RED, bg: "rgba(176,0,32,0.10)" },
  disabled: { word: "Paused", color: MUTED, bg: "rgba(107,114,128,0.12)" },
};

// Rollup bucket order + per-bucket hue. Only non-zero buckets render, joined by " · ".
const BUCKETS: { key: keyof FolderCounts; label: string; color: string }[] = [
  { key: "synced", label: "synced", color: GREEN },
  { key: "indexing", label: "indexing", color: AMBER },
  { key: "pending", label: "pending", color: AMBER },
  { key: "stale", label: "stale", color: AMBER },
  { key: "error", label: "error", color: RED },
  { key: "deleted", label: "deleted", color: MUTED },
];

interface FolderSourceCardProps {
  folder: FolderSource;
  token: string;
  // Perform the DELETE (owned by the hook so the list updates). The dialog calls this on confirm.
  onRemove: (id: string) => Promise<void>;
}

/** One folder-source card (#458): label, truncated path, a word+color status pill, a live rollup of
 * the non-zero file buckets (driven by the SSE stream while mounted), and Pause/Resume (optimistic),
 * Re-sync (disabled while scanning; surfaces E_FOLDER_PAUSED), and Remove (opens a confirm dialog). */
export function FolderSourceCard({
  folder,
  token,
  onRemove,
}: FolderSourceCardProps): React.ReactElement {
  // Local copy so the SSE stream + optimistic pause/resume can update this card without a parent
  // refetch. Re-synced to props when the parent replaces the folder object (add/remove refresh).
  const [status, setStatus] = useState<FolderStatus>(folder.status);
  const [counts, setCounts] = useState<FolderCounts>(folder.counts);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [resyncNotice, setResyncNotice] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  // Drill-down (#458 pass 2): FolderDetail mounts only when expanded, lazy-fetching the file list.
  const [expanded, setExpanded] = useState(false);

  // Reconcile with the authoritative prop when the parent hands a new folder object (e.g. after the
  // list refresh that follows an add). SSE/optimistic updates ride on top between these resets.
  useEffect(() => {
    setStatus(folder.status);
    setCounts(folder.counts);
  }, [folder]);

  // Live scan progress: open the SSE stream while the card is mounted; abort (close) on unmount.
  useEffect(() => {
    const controller = new AbortController();
    void streamFolderEvents(
      folder.id,
      (ev) => {
        setStatus(ev.status);
        setCounts(ev.counts);
      },
      token,
      controller.signal,
    );
    return () => controller.abort();
  }, [folder.id, token]);

  const segments = BUCKETS.map((b) => ({ ...b, n: counts[b.key] ?? 0 })).filter((b) => b.n > 0);
  const pill = STATUS_PILL[status];
  const name = folder.label || folder.root_path;

  async function pause(): Promise<void> {
    const prev = status;
    setBusy(true);
    setActionError(null);
    setStatus("disabled"); // optimistic
    try {
      const updated = await pauseFolder(token, folder.id);
      setStatus(updated.status);
      setCounts(updated.counts);
    } catch {
      setStatus(prev); // revert on failure
      setActionError("Could not pause this source.");
    } finally {
      setBusy(false);
    }
  }

  async function resume(): Promise<void> {
    const prev = status;
    setBusy(true);
    setActionError(null);
    setResyncNotice(null);
    setStatus("scanning"); // optimistic — resuming kicks off a re-scan
    try {
      const updated = await resumeFolder(token, folder.id);
      setStatus(updated.status);
      setCounts(updated.counts);
    } catch {
      setStatus(prev); // revert on failure
      setActionError("Could not resume this source.");
    } finally {
      setBusy(false);
    }
  }

  async function resync(): Promise<void> {
    setBusy(true);
    setActionError(null);
    setResyncNotice(null);
    try {
      const result = await resyncFolder(token, folder.id);
      if (result.ok) {
        setStatus("scanning");
      } else {
        // E_FOLDER_PAUSED (or any structured error) is shown inline, not thrown.
        setResyncNotice(result.error.message);
      }
    } catch {
      setActionError("Could not start a re-sync.");
    } finally {
      setBusy(false);
    }
  }

  const isPaused = status === "disabled";
  const isScanning = status === "scanning";

  const btn = (extra: React.CSSProperties): React.CSSProperties => ({
    padding: "0.3rem 0.6rem",
    border: "1px solid #ddd",
    borderRadius: 6,
    background: "none",
    fontSize: "0.78rem",
    cursor: "pointer",
    color: "#333",
    ...extra,
  });

  return (
    <li
      data-testid="folder-card"
      data-folder-id={folder.id}
      data-status={status}
      style={{
        listStyle: "none",
        border: "1px solid #e2e2e2",
        borderRadius: 8,
        padding: "0.7rem 0.8rem",
        display: "flex",
        flexDirection: "column",
        gap: "0.45rem",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <button
          data-testid="folder-expand-toggle"
          type="button"
          aria-expanded={expanded}
          aria-label={expanded ? `Collapse ${name}` : `Expand ${name}`}
          onClick={() => setExpanded((v) => !v)}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: MUTED,
            fontSize: "0.8rem",
            padding: 0,
            lineHeight: 1,
            flex: "0 0 auto",
          }}
        >
          <span aria-hidden>{expanded ? "▾" : "▸"}</span>
        </button>
        <strong
          style={{
            fontSize: "0.9rem",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            maxWidth: "16em",
          }}
          title={name}
        >
          {name}
        </strong>
        <span
          data-testid="folder-status"
          style={{
            color: pill.color,
            background: pill.bg,
            borderRadius: 8,
            padding: "0 0.45rem",
            fontSize: "0.72rem",
            fontWeight: 600,
            flex: "0 0 auto",
          }}
        >
          {pill.word}
        </span>
      </div>

      {/* Full path in title + aria-label; the visible text truncates with an ellipsis. */}
      <div
        data-testid="folder-path"
        title={folder.root_path}
        aria-label={folder.root_path}
        style={{
          color: MUTED,
          fontSize: "0.78rem",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          direction: "rtl", // keep the meaningful tail (deepest folder) visible when truncated
          textAlign: "left",
        }}
      >
        {folder.root_path}
      </div>

      {/* Live rollup: only the non-zero buckets, updated by the SSE stream. aria-live so the change
          is announced. Word + color per bucket (never color alone). */}
      <div
        data-testid="folder-rollup"
        aria-live="polite"
        style={{ fontSize: "0.78rem", display: "flex", flexWrap: "wrap", gap: "0.25rem" }}
      >
        {segments.length === 0 ? (
          <span style={{ color: MUTED }}>No files indexed yet</span>
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
      </div>

      {folder.status_detail && status === "error" && (
        <div data-testid="folder-status-detail" style={{ color: RED, fontSize: "0.76rem" }}>
          {folder.status_detail}
        </div>
      )}

      {resyncNotice && (
        <div
          data-testid="folder-resync-notice"
          role="status"
          aria-live="polite"
          style={{ color: AMBER, fontSize: "0.76rem" }}
        >
          {resyncNotice}
        </div>
      )}
      {actionError && (
        <div
          data-testid="folder-card-error"
          role="alert"
          aria-live="assertive"
          style={{ color: RED, fontSize: "0.76rem" }}
        >
          {actionError}
        </div>
      )}

      <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
        {isPaused ? (
          <button
            data-testid="folder-resume"
            type="button"
            onClick={() => void resume()}
            disabled={busy}
            style={btn({ borderColor: GREEN, color: GREEN })}
          >
            Resume
          </button>
        ) : (
          <button
            data-testid="folder-pause"
            type="button"
            onClick={() => void pause()}
            disabled={busy}
            style={btn({})}
          >
            Pause
          </button>
        )}
        <button
          data-testid="folder-resync"
          type="button"
          onClick={() => void resync()}
          disabled={busy || isScanning}
          title={isScanning ? "A scan is already running" : "Re-scan this folder"}
          style={btn({
            cursor: busy || isScanning ? "not-allowed" : "pointer",
            opacity: isScanning ? 0.6 : 1,
          })}
        >
          Re-sync
        </button>
        <button
          data-testid="folder-remove"
          type="button"
          onClick={() => setDialogOpen(true)}
          disabled={busy}
          style={btn({ borderColor: RED, color: RED, marginLeft: "auto" })}
        >
          Remove
        </button>
      </div>

      {/* Lazy drill-down: mounts (and fetches) only on first expand; unmounts on collapse. */}
      {expanded && <FolderDetail folder={folder} token={token} liveCounts={counts} />}

      {dialogOpen && (
        <RemoveFolderDialog
          // Use the live (SSE/optimistic) status + counts so the purge total the dialog states
          // reflects what is actually indexed right now, not the stale registration snapshot.
          folder={{ ...folder, status, counts }}
          onConfirm={() => onRemove(folder.id)}
          onClose={() => setDialogOpen(false)}
        />
      )}
    </li>
  );
}
