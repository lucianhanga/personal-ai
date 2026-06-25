import { useEffect, useRef, useState } from "react";

// Color code (project convention): green ok, amber warn/in-progress, red error, accent, muted.
const GREEN = "#1a7f37";
const AMBER = "#b06f00";
const RED = "#b00020";
const ACCENT = "#4a90d9";
const MUTED = "#6b7280";

export type AudioStatus = "transcribing" | "done" | "empty" | "error";

export interface AudioAttachment {
  id: string;
  name: string;
  status: AudioStatus;
  transcript: string;
  error?: string;
  // #424: resource-activity facts captured from the transcribe response.
  model?: string | null; // the Whisper model id (may be null)
  ms?: number | null; // transcribe-call wall-clock
}

/** First ~40 chars of the transcript as a one-line snippet for the chip face. */
function snippet(text: string): string {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length > 40 ? `${t.slice(0, 40)}…` : t;
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

/** The floating panel: full transcript (scrollable, bounded) + a Copy button. Only rendered for
 * `done` chips. Dismissed by the parent on Escape/click-away; this owns only the Copy state. */
function TranscriptPanel({ chip }: { chip: AudioAttachment }): React.ReactElement {
  const [copied, setCopied] = useState(false);

  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(chip.transcript);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      // Clipboard blocked (no permission / insecure context) — silently no-op.
    }
  }

  return (
    <div
      data-testid="audio-panel"
      role="dialog"
      aria-label={`Transcript of ${chip.name}`}
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
          data-testid={`copy-audio-${chip.id}`}
          onClick={() => void copy()}
          aria-label="Copy transcript"
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
        {chip.transcript}
      </div>
    </div>
  );
}

function statusCue(chip: AudioAttachment): { color: string; node: React.ReactNode } {
  switch (chip.status) {
    case "transcribing":
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
                animation: "audio-pulse 1s ease-in-out infinite",
              }}
            />
            transcribing…
          </span>
        ),
      };
    case "done":
      return { color: MUTED, node: <span>{snippet(chip.transcript) || "transcript"}</span> };
    case "empty":
      return { color: MUTED, node: <span>no speech</span> };
    case "error":
      return { color: RED, node: <span>{chip.error ?? "transcription failed"}</span> };
  }
}

/** Removable audio attachment chips (drag-drop transcription). Each chip mirrors the image-thumbnail
 * pattern: a glyph + name + state cue + a × remove. `done` chips are focusable and reveal a floating
 * transcript panel on hover/focus/click, with copy-to-clipboard. The panel is "sticky": opening it
 * (hover/focus/click) does NOT auto-close on mouse-leave, so the pointer can travel into the panel to
 * reach Copy; it stays open until an explicit dismissal — Escape, click-away, or re-clicking the chip. */
export function AudioChips({
  chips,
  onRemove,
}: {
  chips: AudioAttachment[];
  onRemove: (id: string) => void;
}): React.ReactElement | null {
  // The chip whose panel is open (hover/focus/click). Only `done` chips can open.
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
      data-testid="audio-attachments"
      style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}
    >
      {/* Keyframes for the transcribing pulse (inline styles can't hold @keyframes). */}
      <style>{"@keyframes audio-pulse{0%,100%{opacity:1}50%{opacity:0.25}}"}</style>
      {chips.map((chip) => {
        const cue = statusCue(chip);
        const canOpen = chip.status === "done";
        const open = canOpen && openId === chip.id;
        return (
          <span
            key={chip.id}
            data-testid="audio-attachment"
            data-status={chip.status}
            tabIndex={0}
            // Open on hover/focus/click. Intentionally NO onMouseLeave/onBlur auto-close: once
            // open the panel STAYS open (so the mouse can travel into it to reach Copy) until an
            // explicit dismissal — Escape, click-away, or clicking the chip again (handled below
            // and by the parent's document listener).
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
            {/* Musical note glyph = audio (monochrome, not emoji). */}
            <span
              aria-hidden="true"
              style={{
                color: chip.status === "done" ? GREEN : ACCENT,
                fontSize: "0.95rem",
                lineHeight: 1,
              }}
            >
              ♪
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
            {/* Separator between filename and the state cue. */}
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
                fontStyle: chip.status === "done" || chip.status === "empty" ? "italic" : "normal",
              }}
            >
              {cue.node}
            </span>
            <button
              data-testid={`remove-audio-${chip.id}`}
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
            {open && <TranscriptPanel chip={chip} />}
          </span>
        );
      })}
    </div>
  );
}
