import { useEffect, useRef, useState } from "react";

// Color code (project convention): green ok, amber warn/in-progress, red error, accent, muted.
const GREEN = "#1a7f37";
const AMBER = "#b06f00";
const RED = "#b00020";
const ACCENT = "#4a90d9";
const MUTED = "#6b7280";

// `small` = extracted text fits the inline token gate (folds inline into the message); `large` = over
// the gate (NOT folded — sent as `documents_full` and ingested into the conversation RAG index at
// send for retrieval-with-citations, Tier-2 ingest-at-send #436/#420).
export type DocumentStatus = "extracting" | "small" | "large" | "error";

export interface DocumentAttachment {
  id: string;
  name: string;
  status: DocumentStatus;
  text: string;
  error?: string;
  // #424: extract-call wall-clock (document parse has no model, so only ms is captured).
  ms?: number | null;
}

/** First ~40 chars of the extracted text as a one-line snippet for the chip face. */
function snippet(text: string): string {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length > 40 ? `${t.slice(0, 40)}…` : t;
}

/** A page-with-lines document glyph (monochrome SVG, not emoji). */
function DocIcon({ color }: { color: string }): React.ReactElement {
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5" />
      <path d="M9 13h6M9 17h6" />
    </svg>
  );
}

/** Classical "two overlapping rounded rectangles" copy glyph (monochrome SVG, not emoji). */
function CopyIcon(): React.ReactElement {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" />
    </svg>
  );
}

/** Check-mark glyph shown briefly after a successful copy (monochrome SVG, not emoji). */
function CheckIcon(): React.ReactElement {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M5 13l4 4L19 7" />
    </svg>
  );
}

/** The floating panel: full extracted text (scrollable, bounded) + a Copy button. Only rendered for
 * `done` chips. Dismissed by the parent on Escape/click-away; this owns only the Copy state. */
function TextPanel({ chip }: { chip: DocumentAttachment }): React.ReactElement {
  const [copied, setCopied] = useState(false);

  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(chip.text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      // Clipboard blocked (no permission / insecure context) — silently no-op.
    }
  }

  return (
    <div
      data-testid="document-panel"
      role="dialog"
      aria-label={`Text of ${chip.name}`}
      // Stop a click inside the panel from bubbling to the document click-away handler.
      onMouseDown={(e) => e.stopPropagation()}
      style={{
        position: "absolute",
        bottom: "calc(100% + 4px)",
        left: 0,
        zIndex: 20,
        minWidth: "18em",
        maxWidth: "min(28em, 80vw)",
        background: "#fff",
        border: "1px solid #e2e2e2",
        borderRadius: 8,
        boxShadow: "0 8px 24px rgba(0,0,0,0.14)",
        overflow: "hidden",
      }}
    >
      {/* Header: filename left, copy icon right. */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.5rem",
          padding: "0.45rem 0.6rem",
          borderBottom: "1px solid #eee",
          background: "rgba(127,127,127,0.04)",
        }}
      >
        <span
          style={{
            color: "#333",
            fontWeight: 600,
            fontSize: "0.78rem",
            flex: 1,
            minWidth: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
          title={chip.name}
        >
          {chip.name}
        </span>
        <button
          data-testid={`copy-document-${chip.id}`}
          onClick={() => void copy()}
          aria-label="Copy document text"
          title={copied ? "Copied" : "Copy"}
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: "1.7em",
            height: "1.7em",
            background: "none",
            border: "1px solid rgba(127,127,127,0.3)",
            borderRadius: 5,
            color: copied ? GREEN : MUTED,
            cursor: "pointer",
            padding: 0,
            flexShrink: 0,
            transition: "color 0.15s",
          }}
        >
          {copied ? <CheckIcon /> : <CopyIcon />}
        </button>
      </div>
      <div
        style={{
          maxHeight: "14em",
          overflow: "auto",
          fontSize: "0.82rem",
          lineHeight: 1.5,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          color: "#222",
          padding: "0.55rem 0.6rem",
        }}
      >
        {chip.text}
      </div>
    </div>
  );
}

function statusCue(chip: DocumentAttachment): { color: string; node: React.ReactNode } {
  switch (chip.status) {
    case "extracting":
      return {
        color: AMBER,
        node: (
          <span role="status" style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
            <span
              aria-hidden="true"
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: AMBER,
                animation: "doc-pulse 1s ease-in-out infinite",
              }}
            />
            extracting…
          </span>
        ),
      };
    case "small":
      return { color: MUTED, node: <span>{snippet(chip.text) || "text"}</span> };
    case "large":
      return { color: AMBER, node: <span>{snippet(chip.text) || "text"}</span> };
    case "error":
      return { color: RED, node: <span>{chip.error ?? "extraction failed"}</span> };
  }
}

/** A small pill clarifying how a `done` document reaches the model (#436): a `small` doc is folded
 * inline into the message ("In message", neutral), a `large` doc is ingested into the conversation
 * RAG index and retrieved with citations ("Searched in this chat", amber/info). No emoji. */
function RetrievalBadge({ status }: { status: DocumentStatus }): React.ReactElement | null {
  if (status !== "small" && status !== "large") return null;
  const isLarge = status === "large";
  const color = isLarge ? AMBER : MUTED;
  const label = isLarge ? "Searched in this chat" : "In message";
  const title = isLarge
    ? "Indexed for retrieval — the assistant searches this document and cites it in this chat."
    : "Folded inline — the full text is included directly in this message.";
  return (
    <span
      data-testid="document-retrieval-badge"
      data-retrieval={isLarge ? "rag" : "inline"}
      title={title}
      style={{
        flexShrink: 0,
        fontSize: "0.66rem",
        fontWeight: 600,
        lineHeight: 1,
        whiteSpace: "nowrap",
        padding: "0.18rem 0.4rem",
        borderRadius: 8,
        color,
        border: `1px solid ${color}`,
        background: isLarge ? "rgba(176,111,0,0.08)" : "rgba(107,114,128,0.08)",
      }}
    >
      {label}
    </span>
  );
}

/** Removable document attachment chips (drag-drop text extraction, #416). Mirrors AudioChips: a
 * document glyph + name + state cue + a × remove. `done` chips are focusable and reveal a floating
 * text panel on hover/focus/click, with copy-to-clipboard. The panel is "sticky": opening it does
 * NOT auto-close on mouse-leave, so the pointer can travel into it to reach Copy; it stays open until
 * an explicit dismissal — Escape, click-away, or re-clicking the chip. */
export function DocumentChips({
  chips,
  onRemove,
}: {
  chips: DocumentAttachment[];
  onRemove: (id: string) => void;
}): React.ReactElement | null {
  const [openId, setOpenId] = useState<string | null>(null);
  const rowRef = useRef<HTMLDivElement>(null);

  // Click-away + Escape dismiss the open panel (a11y: not hover-only).
  useEffect(() => {
    if (openId === null) return;
    function onDocMouseDown(e: MouseEvent): void {
      if (rowRef.current && !rowRef.current.contains(e.target as Node)) setOpenId(null);
    }
    function onKey(e: KeyboardEvent): void {
      if (e.key === "Escape") setOpenId(null);
    }
    document.addEventListener("mousedown", onDocMouseDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocMouseDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [openId]);

  if (chips.length === 0) return null;

  return (
    <div
      ref={rowRef}
      data-testid="document-attachments"
      style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}
    >
      {/* Keyframes for the extracting pulse (inline styles can't hold @keyframes). */}
      <style>{"@keyframes doc-pulse{0%,100%{opacity:1}50%{opacity:0.25}}"}</style>
      {chips.map((chip) => {
        const cue = statusCue(chip);
        // Both small + large have extracted text → the panel (read/copy) opens for either.
        const canOpen = chip.status === "small" || chip.status === "large";
        const open = canOpen && openId === chip.id;
        return (
          <span
            key={chip.id}
            data-testid="document-attachment"
            data-status={chip.status}
            tabIndex={0}
            // Open on hover/focus/click; NO mouse-leave/blur auto-close (sticky — see AudioChips).
            onMouseEnter={() => canOpen && setOpenId(chip.id)}
            onFocus={() => canOpen && setOpenId(chip.id)}
            onClick={() => canOpen && setOpenId((cur) => (cur === chip.id ? null : chip.id))}
            style={{
              position: "relative",
              display: "inline-flex",
              alignItems: "center",
              gap: "0.45rem",
              maxWidth: "22em",
              padding: "0.28rem 0.4rem 0.28rem 0.55rem",
              border: `1px solid ${chip.status === "error" ? RED : open ? ACCENT : "#ddd"}`,
              borderRadius: 14,
              fontSize: "0.8rem",
              background: open ? "rgba(74,144,217,0.08)" : "rgba(127,127,127,0.05)",
              cursor: canOpen ? "pointer" : "default",
              outlineColor: ACCENT,
            }}
          >
            <span style={{ display: "inline-flex", lineHeight: 1 }}>
              <DocIcon color={chip.status === "small" ? GREEN : chip.status === "large" ? AMBER : ACCENT} />
            </span>
            <span
              style={{
                maxWidth: "9em",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                color: "#333",
                fontWeight: 500,
              }}
              title={chip.name}
            >
              {chip.name}
            </span>
            <span aria-hidden="true" style={{ color: "#d0d0d0" }}>
              ·
            </span>
            <span
              style={{
                color: cue.color,
                maxWidth: "11em",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                fontStyle: chip.status === "small" ? "italic" : "normal",
              }}
            >
              {cue.node}
            </span>
            <RetrievalBadge status={chip.status} />
            <button
              data-testid={`remove-document-${chip.id}`}
              onMouseDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                onRemove(chip.id);
              }}
              aria-label={`Remove ${chip.name}`}
              title="Remove"
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: "1.3em",
                height: "1.3em",
                border: "none",
                background: "none",
                color: "#9aa0a6",
                cursor: "pointer",
                fontSize: "0.95rem",
                lineHeight: 1,
                borderRadius: "50%",
                padding: 0,
                flexShrink: 0,
              }}
            >
              ×
            </button>
            {open && <TextPanel chip={chip} />}
          </span>
        );
      })}
    </div>
  );
}

/** A sent document for the transcript (#426): `{ name, text }` reconstructed from the persisted
 * `meta["documents"]`. Always openable (only `done` docs are ever sent). */
export interface TranscriptDocument {
  name: string;
  text: string;
}

/** Read-only document chips for a sent message in the transcript (#426): the same composer hover
 * panel (full extracted text + Copy) and sticky open/Escape/click-away behavior, but with NO remove
 * control and no status cue — every chip is openable. Mirrors `TranscriptImages`/`TranscriptAudio`. */
export function TranscriptDocuments({
  documents,
}: {
  documents: TranscriptDocument[];
}): React.ReactElement | null {
  const [openId, setOpenId] = useState<number | null>(null);
  const rowRef = useRef<HTMLDivElement>(null);

  // Click-away + Escape dismiss the open panel (a11y: not hover-only), matching the composer.
  useEffect(() => {
    if (openId === null) return;
    function onDocMouseDown(e: MouseEvent): void {
      if (rowRef.current && !rowRef.current.contains(e.target as Node)) setOpenId(null);
    }
    function onKey(e: KeyboardEvent): void {
      if (e.key === "Escape") setOpenId(null);
    }
    document.addEventListener("mousedown", onDocMouseDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocMouseDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [openId]);

  if (documents.length === 0) return null;

  return (
    <div
      ref={rowRef}
      data-testid="msg-documents"
      style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}
    >
      {documents.map((doc, i) => {
        const open = openId === i;
        // Reuse the composer's TextPanel shape: a `done` document chip with extracted text.
        const chip: DocumentAttachment = { id: `td-${i}`, name: doc.name, status: "small", text: doc.text };
        return (
          <span
            key={i}
            data-testid="document-attachment"
            data-status="sent"
            tabIndex={0}
            // Open on hover/focus/click; sticky (no auto-close) so the pointer can reach Copy.
            onMouseEnter={() => setOpenId(i)}
            onFocus={() => setOpenId(i)}
            onClick={() => setOpenId((cur) => (cur === i ? null : i))}
            style={{
              position: "relative",
              display: "inline-flex",
              alignItems: "center",
              gap: "0.45rem",
              maxWidth: "22em",
              padding: "0.28rem 0.4rem 0.28rem 0.55rem",
              border: `1px solid ${open ? ACCENT : "#ddd"}`,
              borderRadius: 14,
              fontSize: "0.8rem",
              background: open ? "rgba(74,144,217,0.08)" : "rgba(127,127,127,0.05)",
              cursor: "pointer",
              outlineColor: ACCENT,
            }}
          >
            <span style={{ display: "inline-flex", lineHeight: 1 }}>
              <DocIcon color={GREEN} />
            </span>
            <span
              style={{
                maxWidth: "9em",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                color: "#333",
                fontWeight: 500,
              }}
              title={doc.name}
            >
              {doc.name}
            </span>
            <span aria-hidden="true" style={{ color: "#d0d0d0" }}>
              ·
            </span>
            <span
              style={{
                color: MUTED,
                maxWidth: "11em",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                fontStyle: "italic",
              }}
            >
              {snippet(doc.text) || "text"}
            </span>
            {open && <TextPanel chip={chip} />}
          </span>
        );
      })}
    </div>
  );
}
