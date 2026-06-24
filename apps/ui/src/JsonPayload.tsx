import { useMemo, useState } from "react";

// Truncate the preview at roughly this many characters / lines; the full payload is one click away
// (and Copy always copies the untruncated raw JSON, not the preview).
const MAX_CHARS = 1500;
const MAX_LINES = 24;

// Muted text a user must READ uses #6b7280 (AA); #888/#999 stay decorative.
const READABLE = "#6b7280";

/** Pretty-print an unknown value as JSON; strings pass through, everything else uses 2-space JSON. */
function toJson(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === undefined) return "undefined";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    // Circular / non-serializable — fall back to a best-effort string.
    return String(value);
  }
}

/** Clip text to MAX_CHARS / MAX_LINES, returning the clipped form + whether anything was removed. */
function clip(full: string): { preview: string; clipped: boolean } {
  let preview = full;
  let clipped = false;
  if (preview.length > MAX_CHARS) {
    preview = preview.slice(0, MAX_CHARS);
    clipped = true;
  }
  const lines = preview.split("\n");
  if (lines.length > MAX_LINES) {
    preview = lines.slice(0, MAX_LINES).join("\n");
    clipped = true;
  }
  return { preview, clipped };
}

/**
 * Renders an arbitrary value as scrollable, monospace JSON with a "show full / show less" toggle
 * (preview clipped at ~1.5KB / ~24 lines) and a Copy button that always copies the FULL raw JSON.
 */
export function JsonPayload({ value, label }: { value: unknown; label?: string }): React.ReactElement {
  const full = useMemo(() => toJson(value), [value]);
  const { preview, clipped } = useMemo(() => clip(full), [full]);
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(full);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      // Clipboard blocked (no permission / insecure context) — silently no-op; nothing sensitive.
    }
  }

  const shown = expanded || !clipped ? full : preview;

  return (
    <div data-testid="json-payload" style={{ margin: "2px 0" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: 2 }}>
        {label && <span style={{ color: READABLE, fontWeight: 600 }}>{label}</span>}
        <button
          data-testid="json-copy"
          onClick={copy}
          style={{
            fontSize: "0.7rem",
            background: "none",
            border: "1px solid rgba(127,127,127,0.35)",
            borderRadius: 3,
            color: READABLE,
            cursor: "pointer",
            padding: "0 0.35rem",
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
        {clipped && (
          <button
            data-testid="json-toggle"
            onClick={() => setExpanded((e) => !e)}
            style={{
              fontSize: "0.7rem",
              background: "none",
              border: "none",
              color: READABLE,
              cursor: "pointer",
              padding: 0,
              textDecoration: "underline",
            }}
          >
            {expanded ? "show less" : "show full"}
          </button>
        )}
      </div>
      <pre
        data-testid="json-pre"
        style={{
          margin: 0,
          maxHeight: "16em",
          overflow: "auto",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          fontSize: "0.78rem",
          background: "rgba(127,127,127,0.06)",
          borderRadius: 4,
          padding: "0.35rem 0.5rem",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {shown}
      </pre>
    </div>
  );
}
