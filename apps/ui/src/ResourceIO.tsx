import { useState } from "react";

import type { ResourceAction } from "./api";

// Resource category hue (#424): teal, distinct from tool violet / context accent / reasoning hues.
// AA on white is ~4.7:1 — passes for the 0.72rem/600 label and the spine dot. (UX-owned.)
const RESOURCE = "#0d7d7d";
const OK = "#1a7f37"; // green — done
const ERR = "#b00020"; // red — error
const WARN = "#b06f00"; // amber — in progress
// Muted text a user must READ uses #6b7280 (AA); #888/#999 stay decorative (codebase rule).
const READABLE = "#6b7280";

// A resource node's lifecycle state, derived from the chip status by the caller.
export type ResourceState = "in-progress" | "done" | "error";

// action -> the Tier-1 verb. The ref is appended as " — {ref}". Mirrors the architect's label map.
const ACTION_VERB: Record<ResourceAction, string> = {
  image_described: "Described image",
  document_extracted: "Extracted document",
  document_ocred: "OCR'd document",
  document_vectorized: "Vectorized document",
  document_indexed: "Indexed document",
  audio_transcribed: "Transcribed audio",
};

/** Build the Tier-1 label for a resource activity, e.g. "Described image — cat.jpg". */
export function resourceLabel(action: ResourceAction, ref: string): string {
  return `${ACTION_VERB[action]} — ${ref}`;
}

// ms -> short human duration; mirrors ActivityTimeline's local fmtMs so the panel reads consistently.
function fmtMs(ms: number): string {
  return ms < 1000
    ? `${Math.round(ms)} ms`
    : ms < 60000
      ? `${(ms / 1000).toFixed(1)} s`
      : `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}

/** The Tier-1 status pill: words + color (never color-only). green done / red error / amber in-flight. */
function StatusPill({ state }: { state: ResourceState }): React.ReactElement {
  const map = {
    "in-progress": { color: WARN, bg: "rgba(176,111,0,0.10)", text: "in progress" },
    done: { color: OK, bg: "rgba(26,127,55,0.12)", text: "done" },
    error: { color: ERR, bg: "rgba(176,0,32,0.10)", text: "error" },
  } as const;
  const { color, bg, text } = map[state];
  return (
    <span
      data-testid="resourceio-status"
      style={{ color, background: bg, borderRadius: 8, padding: "0 0.4rem", fontSize: "0.72rem", fontWeight: 600 }}
    >
      {text}
    </span>
  );
}

/**
 * One eager resource-processing activity (image describe / doc extract / audio transcribe) shown as
 * progressive disclosure, structurally identical to ToolIO so it reads as a sibling tool chip:
 * Tier 1 is a clickable summary line (caret + "Resource" + action label + status pill); Tier 2 reveals
 * the model, duration, ref, and (on error) the message. Color, not glyph — no emoji (#424).
 */
export function ResourceIO({
  action,
  refName,
  state,
  model,
  ms,
  note,
  error,
}: {
  action: ResourceAction;
  refName: string;
  state: ResourceState;
  model?: string | null;
  ms?: number | null;
  note?: string | null;
  error?: string | null;
}): React.ReactElement {
  const [open, setOpen] = useState<boolean>(false);
  const label = resourceLabel(action, refName);

  return (
    <div
      data-testid="timeline-resource"
      data-status={state}
      style={{ background: "#e6f4f4", borderRadius: 3, padding: "1px 5px", margin: "1px 0" }}
    >
      {/* Tier 1: always-visible summary; clicking toggles Tier 2 (keyboard-operable via the button). */}
      <button
        data-testid="resourceio-summary"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.4rem",
          width: "100%",
          background: "none",
          border: "none",
          cursor: "pointer",
          padding: "1px 0",
          textAlign: "left",
          font: "inherit",
        }}
      >
        <span aria-hidden style={{ color: READABLE, fontSize: "0.72rem" }}>{open ? "▾" : "▸"}</span>
        <span style={{ color: RESOURCE, fontWeight: 600 }}>Resource</span>
        <span
          style={{ color: "#1f2937", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
        >
          {label}
        </span>
        <span style={{ marginLeft: "auto", flex: "0 0 auto" }}>
          <StatusPill state={state} />
        </span>
      </button>

      {/* Tier 2: model + duration + ref (+ error), collapsed by default. */}
      {open && (
        <div data-testid="resourceio-detail" style={{ paddingLeft: "0.9rem", paddingBottom: "0.25rem" }}>
          {model ? (
            <div style={{ color: READABLE, fontSize: "0.78rem" }}>
              <strong style={{ fontWeight: 600 }}>Model:</strong> {model}
            </div>
          ) : state === "in-progress" ? (
            <div style={{ color: READABLE, fontSize: "0.78rem" }}>working…</div>
          ) : null}
          {note ? (
            <div data-testid="resourceio-note" style={{ color: READABLE, fontSize: "0.78rem" }}>
              <strong style={{ fontWeight: 600 }}>Detail:</strong> {note}
            </div>
          ) : null}
          {ms != null && (
            <div style={{ color: READABLE, fontSize: "0.78rem" }}>
              <strong style={{ fontWeight: 600 }}>Duration:</strong> {fmtMs(ms)}
            </div>
          )}
          <div style={{ color: READABLE, fontSize: "0.78rem" }}>
            <strong style={{ fontWeight: 600 }}>Resource:</strong> {refName}
          </div>
          {state === "error" && error && (
            <div
              data-testid="resourceio-error"
              style={{ color: ERR, fontSize: "0.78rem", margin: "2px 0", whiteSpace: "pre-wrap" }}
            >
              {error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
