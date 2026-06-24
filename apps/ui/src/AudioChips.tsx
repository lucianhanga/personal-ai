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
}

/** First ~40 chars of the transcript as a one-line snippet for the chip face. */
function snippet(text: string): string {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length > 40 ? `${t.slice(0, 40)}…` : t;
}

/** The floating panel: full transcript (scrollable, bounded) + a Copy button. Only rendered for
 * `done` chips. Dismissed by the parent on blur/Escape/click-away; this owns only the Copy state. */
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
        bottom: "calc(100% + 6px)",
        left: 0,
        zIndex: 20,
        minWidth: "16em",
        maxWidth: "min(28em, 80vw)",
        background: "#fff",
        border: "1px solid #ddd",
        borderRadius: 6,
        boxShadow: "0 6px 18px rgba(0,0,0,0.12)",
        padding: "0.5rem",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: 4 }}>
        <span style={{ color: MUTED, fontWeight: 600, fontSize: "0.78rem", flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {chip.name}
        </span>
        <button
          data-testid={`copy-audio-${chip.id}`}
          onClick={() => void copy()}
          style={{
            fontSize: "0.7rem",
            background: "none",
            border: "1px solid rgba(127,127,127,0.35)",
            borderRadius: 3,
            color: MUTED,
            cursor: "pointer",
            padding: "0 0.35rem",
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <div
        style={{
          maxHeight: "14em",
          overflow: "auto",
          fontSize: "0.82rem",
          lineHeight: 1.4,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
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
 * transcript panel on hover/focus/click, with copy-to-clipboard. */
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
            onMouseEnter={() => canOpen && setOpenId(chip.id)}
            onMouseLeave={() => setOpenId((cur) => (cur === chip.id ? null : cur))}
            onFocus={() => canOpen && setOpenId(chip.id)}
            onClick={() => canOpen && setOpenId((cur) => (cur === chip.id ? null : chip.id))}
            style={{
              position: "relative",
              display: "inline-flex",
              alignItems: "center",
              gap: "0.4rem",
              maxWidth: "22em",
              padding: "0.2rem 0.45rem",
              border: `1px solid ${chip.status === "error" ? RED : "#ddd"}`,
              borderRadius: 14,
              fontSize: "0.8rem",
              background: "rgba(127,127,127,0.05)",
              cursor: canOpen ? "pointer" : "default",
              outlineColor: ACCENT,
            }}
          >
            {/* Musical note glyph = audio (monochrome, not emoji). */}
            <span aria-hidden="true" style={{ color: chip.status === "done" ? GREEN : ACCENT }}>
              ♪
            </span>
            <span
              style={{
                maxWidth: "9em",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                color: "#333",
              }}
              title={chip.name}
            >
              {chip.name}
            </span>
            <span style={{ color: cue.color, maxWidth: "11em", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
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
                border: "none",
                background: "none",
                color: MUTED,
                cursor: "pointer",
                fontSize: "1rem",
                lineHeight: 1,
                padding: "0 0.1rem",
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
