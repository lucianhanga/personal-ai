import { useEffect, useRef, useState } from "react";

import type { FolderSource } from "./api";

const RED = "#b00020";
const MUTED = "#6b7280";

// Total indexed items a removal would purge — the sum of the non-deleted lifecycle buckets. Shown so
// the dialog states exactly what is destroyed before the user confirms.
function indexedCount(folder: FolderSource): number {
  const c = folder.counts;
  return (
    (c.pending ?? 0) + (c.indexing ?? 0) + (c.synced ?? 0) + (c.stale ?? 0) + (c.error ?? 0)
  );
}

interface RemoveFolderDialogProps {
  folder: FolderSource;
  // Perform the delete. Resolves when done (the parent then drops the card); rejects to surface here.
  onConfirm: () => Promise<void>;
  onClose: () => void;
}

/** The destructive-confirm dialog for removing a folder source (#458). Modal + focus-trapped: default
 * focus is Cancel (the safe choice), Tab cycles within the dialog, Escape closes. Only confirming
 * here triggers the DELETE; it states exactly how many indexed chunks/entities are purged. */
export function RemoveFolderDialog({
  folder,
  onConfirm,
  onClose,
}: RemoveFolderDialogProps): React.ReactElement {
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Default focus on Cancel (the safe action) when the dialog opens.
  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  // Escape closes; Tab/Shift+Tab is trapped within the dialog's focusable controls.
  useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const root = dialogRef.current;
      if (!root) return;
      const focusable = root.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input, [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeEl = document.activeElement;
      if (e.shiftKey && activeEl === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && activeEl === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function confirm(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      // The parent unmounts the card (and this dialog) on success; no further state needed here.
    } catch {
      setError("Could not remove the folder source. Please try again.");
      setBusy(false);
    }
  }

  const count = indexedCount(folder);
  const name = folder.label || folder.root_path;

  return (
    <div
      // Backdrop: a click outside the dialog body cancels (mousedown to beat focus shifts).
      data-testid="remove-folder-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.35)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 50,
      }}
    >
      <div
        ref={dialogRef}
        data-testid="remove-folder-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="remove-folder-title"
        aria-describedby="remove-folder-message"
        onMouseDown={(e) => e.stopPropagation()}
        style={{
          background: "#fff",
          borderRadius: 10,
          padding: "1.25rem",
          maxWidth: "26em",
          width: "90%",
          boxShadow: "0 12px 40px rgba(0,0,0,0.25)",
        }}
      >
        <h2 id="remove-folder-title" style={{ margin: "0 0 0.5rem", fontSize: "1rem" }}>
          Remove folder source
        </h2>
        <p
          id="remove-folder-message"
          data-testid="remove-folder-message"
          style={{ margin: "0 0 1rem", fontSize: "0.85rem", color: "#333", lineHeight: 1.5 }}
        >
          Removing <strong>{name}</strong> stops watching the folder and deletes its{" "}
          <strong>{count}</strong> indexed {count === 1 ? "chunk/entity" : "chunks/entities"} from the
          search index. This cannot be undone.
        </p>

        {error && (
          <p
            data-testid="remove-folder-error"
            role="alert"
            aria-live="assertive"
            style={{ color: RED, fontSize: "0.8rem", margin: "0 0 0.75rem" }}
          >
            {error}
          </p>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
          <button
            ref={cancelRef}
            data-testid="remove-folder-cancel"
            type="button"
            onClick={onClose}
            disabled={busy}
            style={{
              padding: "0.4rem 0.9rem",
              border: "1px solid #ddd",
              borderRadius: 6,
              background: "none",
              color: MUTED,
              fontSize: "0.85rem",
              cursor: busy ? "not-allowed" : "pointer",
            }}
          >
            Cancel
          </button>
          <button
            data-testid="remove-folder-confirm"
            type="button"
            onClick={() => void confirm()}
            disabled={busy}
            style={{
              padding: "0.4rem 0.9rem",
              border: `1px solid ${RED}`,
              borderRadius: 6,
              background: RED,
              color: "#fff",
              fontSize: "0.85rem",
              fontWeight: 600,
              cursor: busy ? "not-allowed" : "pointer",
              opacity: busy ? 0.7 : 1,
            }}
          >
            {busy ? "Removing…" : "Remove"}
          </button>
        </div>
      </div>
    </div>
  );
}
