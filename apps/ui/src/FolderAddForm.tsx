import { useState } from "react";

import type { AddFolderResult } from "./useFolderSources";

// Color code (project convention): green ok, amber warn, red error, muted readable.
const RED = "#b00020";
const MUTED = "#6b7280";

interface FolderAddFormProps {
  // Register the source. Resolves to a discriminated result: on success the form clears; on failure
  // the structured backend message is shown inline.
  onAdd: (path: string, label: string) => Promise<AddFolderResult>;
  // Offline / backend-down: the inputs + submit are disabled (no mutating action possible).
  disabled?: boolean;
  // Optional: dismiss the form (the parent's "Add folder source" toggle).
  onCancel?: () => void;
}

/** The add-a-folder-source form (#458): a path + optional label + Add. On a structured backend error
 * (E_FOLDER_NOT_FOUND / E_FOLDER_NOT_A_DIR / E_FOLDER_EXISTS) the specific message renders inline;
 * on success the inputs clear and the parent refreshes the list. */
export function FolderAddForm({ onAdd, disabled, onCancel }: FolderAddFormProps): React.ReactElement {
  const [path, setPath] = useState("");
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const trimmedPath = path.trim();
  const canSubmit = trimmedPath.length > 0 && !submitting && !disabled;

  async function submit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await onAdd(trimmedPath, label.trim());
      if (result.ok) {
        setPath("");
        setLabel("");
      } else {
        setError(result.error.message);
      }
    } catch {
      setError("Could not add the folder source. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  const inputStyle: React.CSSProperties = {
    width: "100%",
    boxSizing: "border-box",
    padding: "0.35rem 0.5rem",
    border: "1px solid #ddd",
    borderRadius: 6,
    fontSize: "0.85rem",
  };

  return (
    <form
      data-testid="folder-add-form"
      onSubmit={(e) => void submit(e)}
      aria-label="Add folder source"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.5rem",
        border: "1px solid #e2e2e2",
        borderRadius: 8,
        padding: "0.75rem",
        margin: "0.5rem 0",
        background: "rgba(127,127,127,0.03)",
      }}
    >
      <label style={{ fontSize: "0.8rem", color: MUTED }}>
        Folder path
        <input
          data-testid="folder-add-path"
          type="text"
          value={path}
          disabled={disabled}
          onChange={(e) => setPath(e.target.value)}
          placeholder="/Users/me/Documents/notes"
          autoComplete="off"
          spellCheck={false}
          aria-invalid={error != null}
          aria-describedby={error ? "folder-add-error" : undefined}
          style={{ ...inputStyle, marginTop: "0.2rem" }}
        />
      </label>
      <label style={{ fontSize: "0.8rem", color: MUTED }}>
        Label <span style={{ color: "#9aa0a6" }}>(optional)</span>
        <input
          data-testid="folder-add-label"
          type="text"
          value={label}
          disabled={disabled}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="My notes"
          autoComplete="off"
          style={{ ...inputStyle, marginTop: "0.2rem" }}
        />
      </label>

      {error && (
        <p
          id="folder-add-error"
          data-testid="folder-add-error"
          role="alert"
          aria-live="assertive"
          style={{ color: RED, fontSize: "0.8rem", margin: 0 }}
        >
          {error}
        </p>
      )}

      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
        <button
          data-testid="folder-add-submit"
          type="submit"
          disabled={!canSubmit}
          style={{
            padding: "0.35rem 0.8rem",
            border: "1px solid #1a7f37",
            borderRadius: 6,
            background: canSubmit ? "#1a7f37" : "#9aa0a6",
            color: "#fff",
            fontSize: "0.82rem",
            fontWeight: 600,
            cursor: canSubmit ? "pointer" : "not-allowed",
          }}
        >
          {submitting ? "Adding…" : "Add"}
        </button>
        {onCancel && (
          <button
            data-testid="folder-add-cancel"
            type="button"
            onClick={onCancel}
            style={{
              padding: "0.35rem 0.8rem",
              border: "1px solid #ddd",
              borderRadius: 6,
              background: "none",
              color: MUTED,
              fontSize: "0.82rem",
              cursor: "pointer",
            }}
          >
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
