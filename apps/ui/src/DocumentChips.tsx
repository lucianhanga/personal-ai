import { useEffect, useRef, useState } from "react";

// Color code (project convention): green ok, amber warn/in-progress, red error, accent, muted.
const GREEN = "#1a7f37";
const AMBER = "#b06f00";
const RED = "#b00020";
const ACCENT = "#4a90d9";
const MUTED = "#6b7280";

// `small` = extracted text fits the inline token gate (folds inline into the message); `large` = over
// the gate (NOT folded — sent as `documents_full` and ingested into the conversation RAG index at
// send for retrieval-with-citations, Tier-2 ingest-at-send #436/#420). `empty` = the parse returned
// no selectable text (a scanned / image-only PDF — pypdf does NOT OCR; #446): NOT an extraction
// failure, so it is shown as an explained empty-state (mirrors AudioChips' "no speech") and is NOT
// folded into the message / not RAG-ingested.
export type DocumentStatus = "extracting" | "small" | "large" | "empty" | "error";

// The explanation shown in the panel of an `empty` doc (#446). The panel still opens so the user can
// read WHY the chip is blank rather than seeing nothing.
export const EMPTY_DOC_EXPLANATION =
  "This PDF appears to be scanned or image-only — it has no embedded text layer, so nothing " +
  "could be extracted. Viewers like Preview can still let you select text because they run OCR " +
  "on the page images as you view them; that text isn't stored in the file. Automatic OCR isn't " +
  "supported here yet.";

export interface DocumentAttachment {
  id: string;
  name: string;
  status: DocumentStatus;
  text: string;
  error?: string;
  // #424: extract-call wall-clock (document parse has no model, so only ms is captured).
  ms?: number | null;
  // Tier-2 ingest-at-attach (#420): a `large` doc is indexed into the conversation RAG scope eagerly
  // when attached. `ragState` tracks that so the badge is truthful: "indexing" while embedding,
  // "indexed" once done, "failed" if ingest errored. Undefined until eager ingest starts.
  ragState?: "indexing" | "indexed" | "failed";
  // #450 document-pipeline metadata, surfaced as Activity stages (OCR -> extract -> vectorize ->
  // index). `ocr`/`pages` come from extraction; `chunks`/`embedModel`/`vectorizeMs` from eager ingest.
  ocr?: boolean;
  pages?: number | null;
  chunks?: number | null;
  embedModel?: string | null;
  vectorizeMs?: number | null;
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

/** The floating panel: full extracted text (scrollable, bounded) + a Copy button. Rendered for chips
 * that have text (`small`/`large`/sent), and for `empty` chips where it explains WHY the doc is blank
 * (a scanned / image-only PDF, #446) instead of leaving the panel empty. Dismissed by the parent on
 * Escape/click-away; this owns only the Copy state. */
function TextPanel({ chip }: { chip: DocumentAttachment }): React.ReactElement {
  const [copied, setCopied] = useState(false);
  // An `empty` doc has no extractable text (#446): show the explanation, no Copy (nothing to copy).
  const isEmpty = chip.status === "empty";

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
        {/* Empty docs have nothing to copy — hide the Copy control (#446). */}
        {!isEmpty && (
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
        )}
      </div>
      <div
        data-testid={isEmpty ? "document-empty-explanation" : undefined}
        style={{
          maxHeight: "14em",
          overflow: "auto",
          fontSize: "0.82rem",
          lineHeight: 1.5,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          // The explanation is informational (muted/italic), not the document's own text.
          color: isEmpty ? MUTED : "#222",
          fontStyle: isEmpty ? "italic" : "normal",
          padding: "0.55rem 0.6rem",
        }}
      >
        {isEmpty ? EMPTY_DOC_EXPLANATION : chip.text}
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
    case "empty":
      // Scanned / image-only PDF — no selectable text (#446). NOT an error (muted, not red); the
      // panel explains it. Mirrors AudioChips' "no speech".
      return { color: MUTED, node: <span>no text found</span> };
    case "error":
      return { color: RED, node: <span>{chip.error ?? "extraction failed"}</span> };
  }
}

/** A small pill clarifying how a `done` document reaches the model (#436): a `small` doc is folded
 * inline into the message ("In message", neutral), a `large` doc is ingested into the conversation
 * RAG index and retrieved with citations. For large docs the label is TRUTHFUL to the eager
 * ingest-at-attach state (#420): "Indexing…" while embedding, "Searched in this chat" once indexed,
 * "Indexes on send" if eager ingest failed or hasn't run (it still ingests at send). No emoji. */
function RetrievalBadge({
  status,
  ragState,
}: {
  status: DocumentStatus;
  ragState?: DocumentAttachment["ragState"];
}): React.ReactElement | null {
  if (status !== "small" && status !== "large") return null;
  const isLarge = status === "large";
  const color = isLarge ? AMBER : MUTED;
  let label: string;
  let title: string;
  if (!isLarge) {
    label = "In message";
    title = "Folded inline — the full text is included directly in this message.";
  } else if (ragState === "indexing") {
    label = "Indexing…";
    title = "Embedding this document into the chat's index so it can be searched and cited.";
  } else if (ragState === "failed") {
    label = "Indexes on send";
    title = "Eager indexing didn't complete; the document is indexed when you send your message.";
  } else {
    // "indexed" (eager ingest done) or undefined (legacy / indexes at send) — both searchable.
    label = "Searched in this chat";
    title = "Indexed — the assistant searches this document and cites it in this chat.";
  }
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
        // small + large have extracted text → the panel (read/copy) opens for either; `empty` opens
        // too, to show the scanned/image-only explanation rather than a blank panel (#446).
        const canOpen =
          chip.status === "small" || chip.status === "large" || chip.status === "empty";
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
              <DocIcon
                color={
                  chip.status === "small"
                    ? GREEN
                    : chip.status === "large"
                      ? AMBER
                      : chip.status === "empty"
                        ? MUTED
                        : ACCENT
                }
              />
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
                fontStyle: chip.status === "small" || chip.status === "empty" ? "italic" : "normal",
              }}
            >
              {cue.node}
            </span>
            <RetrievalBadge status={chip.status} ragState={chip.ragState} />
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
