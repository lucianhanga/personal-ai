import { useState } from "react";

import type { ContextBreakdown, UsageInfo } from "./api";

// localStorage key for the composition section's open/closed state (default open).
const OPEN_KEY = "personalai_context_open";

// Plain-language, one-sentence explanations per composition source, keyed by a normalized label.
// Falls back to a generic line for any source we don't have copy for yet.
const EXPLANATIONS: Record<string, string> = {
  system: "The assistant's base instructions and persona.",
  memory: "Facts saved from past chats that the assistant is allowed to recall.",
  documents: "Passages retrieved from files you uploaded, matched to your question.",
  history: "Earlier messages from this conversation, for continuity.",
  tools: "Definitions of the tools the assistant may call this turn.",
  question: "Your current message.",
};
const GENERIC_EXPL = "Included in the prompt for this turn.";

function explain(label: string): string {
  return EXPLANATIONS[label.trim().toLowerCase()] ?? GENERIC_EXPL;
}

const fmt = (n: number): string => n.toLocaleString();
// Rough token estimate from characters (~4 chars/token) for the per-component composition view.
const approxTokens = (chars: number): number => Math.max(1, Math.round(chars / 4));
// Milliseconds -> a short human duration ("820 ms", "2.3 s", "1m 5s").
const fmtMs = (ms: number): string =>
  ms < 1000
    ? `${Math.round(ms)} ms`
    : ms < 60000
      ? `${(ms / 1000).toFixed(1)} s`
      : `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;

const BAR = "#4a90d9";

/** Show what's in the model's context this turn (composition) and how full the window is (usage). */
export function ContextMeter({
  usage,
  totals,
  context,
}: {
  usage: UsageInfo | null;
  totals?: { tokens: number; ms: number; turns: number };
  context: ContextBreakdown | null;
}): React.ReactElement {
  const prompt = usage?.prompt_tokens ?? 0;
  const limit = usage?.context_limit ?? null;
  const pct = limit ? Math.min(100, Math.round((prompt / limit) * 100)) : null;
  // Green under 70%, amber under 90%, red at/over 90%.
  const color = pct === null ? BAR : pct < 70 ? "#2a9d4a" : pct < 90 ? "#b06f00" : "#b00";
  // Which composition row's token overlay is showing (on hover).
  const [hovered, setHovered] = useState<string | null>(null);
  // Collapsible composition section; persisted so the choice survives reloads (default open).
  const [open, setOpen] = useState<boolean>(() => {
    try {
      return localStorage.getItem(OPEN_KEY) !== "0";
    } catch {
      return true;
    }
  });
  // Which row's plain-language explanation popover is open (keyboard/tap toggle, AA-readable).
  const [expl, setExpl] = useState<string | null>(null);

  function toggleOpen(): void {
    setOpen((o) => {
      const next = !o;
      try {
        localStorage.setItem(OPEN_KEY, next ? "1" : "0");
      } catch {
        // Storage unavailable (private mode / blocked) — state still works for the session.
      }
      return next;
    });
  }

  return (
    <div
      data-testid="context-meter"
      style={{ fontSize: "0.72rem", color: "#555", margin: "0.25rem 0" }}
    >
      {/* Collapsible header: toggles the composition breakdown; choice persists in localStorage. */}
      <button
        data-testid="context-collapse-toggle"
        aria-expanded={open}
        onClick={toggleOpen}
        style={{
          fontWeight: 600,
          marginBottom: 3,
          background: "none",
          border: "none",
          color: "inherit",
          cursor: "pointer",
          padding: 0,
          font: "inherit",
        }}
      >
        {open ? "▾" : "▸"} Context
      </button>

      {/* Composition: what was assembled into the prompt this turn (shown as the question is asked). */}
      {open && context && context.items.length > 0 && (
        <div data-testid="context-breakdown" style={{ marginBottom: usage ? "0.4rem" : 0 }}>
          {context.items.map((it) => {
            const share = context.total_chars
              ? Math.round((it.chars / context.total_chars) * 100)
              : 0;
            const tokens = approxTokens(it.chars);
            return (
              <div
                key={it.label}
                data-testid="context-item"
                onMouseEnter={() => setHovered(it.label)}
                onMouseLeave={() => setHovered((h) => (h === it.label ? null : h))}
                style={{ marginBottom: 3, position: "relative", cursor: "default" }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
                    {it.label}
                    {it.count > 1 ? ` (${it.count})` : ""}
                    {/* Keyboard-focusable + tap-friendly explanation of this source (not hover-only). */}
                    <button
                      data-testid="context-help-btn"
                      type="button"
                      tabIndex={0}
                      aria-label={`What is ${it.label}?`}
                      aria-expanded={expl === it.label}
                      onClick={(e) => {
                        e.stopPropagation();
                        setExpl((c) => (c === it.label ? null : it.label));
                      }}
                      style={{
                        width: 14,
                        height: 14,
                        lineHeight: "12px",
                        fontSize: "0.62rem",
                        borderRadius: "50%",
                        border: "1px solid rgba(127,127,127,0.5)",
                        background: "none",
                        color: "#6b7280",
                        cursor: "pointer",
                        padding: 0,
                      }}
                    >
                      ?
                    </button>
                  </span>
                  <span style={{ color: "#888" }}>~{fmt(tokens)} tok</span>
                </div>
                {expl === it.label && (
                  <div
                    data-testid="context-expl"
                    role="note"
                    style={{
                      marginTop: 2,
                      color: "#6b7280",
                      background: "rgba(127,127,127,0.08)",
                      borderRadius: 4,
                      padding: "0.25rem 0.4rem",
                    }}
                  >
                    {explain(it.label)}
                  </div>
                )}
                <div style={{ height: 4, borderRadius: 3, background: "rgba(127,127,127,0.15)" }}>
                  <div style={{ width: `${share}%`, height: "100%", background: BAR, borderRadius: 3 }} />
                </div>
                {hovered === it.label && (
                  <div
                    data-testid="context-tooltip"
                    role="tooltip"
                    style={{
                      position: "absolute",
                      zIndex: 20,
                      top: "100%",
                      left: 0,
                      marginTop: 3,
                      background: "#1f2937",
                      color: "#fff",
                      borderRadius: 4,
                      padding: "0.35rem 0.5rem",
                      fontSize: "0.72rem",
                      whiteSpace: "nowrap",
                      boxShadow: "0 2px 8px rgba(0,0,0,0.25)",
                    }}
                  >
                    <strong>
                      {it.label}
                      {it.count > 1 ? ` (${it.count} parts)` : ""}
                    </strong>
                    <br />~{fmt(tokens)} tokens · {fmt(it.chars)} chars · {share}% of context
                  </div>
                )}
              </div>
            );
          })}
          <div style={{ color: "#888", marginTop: 2 }}>
            Assembled ~{fmt(approxTokens(context.total_chars))} tokens (estimate)
          </div>
        </div>
      )}

      {/* Actual window usage, reported after the turn completes. */}
      {usage && (
        <>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
            <span style={{ color: "#888" }}>Window</span>
            <span data-testid="context-meter-label">
              {limit ? (
                <>
                  {fmt(prompt)} / {fmt(limit)} ({pct}%)
                </>
              ) : (
                <>{fmt(prompt)} prompt tokens</>
              )}
              {usage.completion_tokens != null && <> · +{fmt(usage.completion_tokens)} reply</>}
              {usage.elapsed_ms != null && (
                <span data-testid="usage-time"> · {fmtMs(usage.elapsed_ms)}</span>
              )}
            </span>
          </div>
          {pct !== null && (
            <div
              aria-hidden
              style={{ height: 6, borderRadius: 4, background: "rgba(127,127,127,0.2)", overflow: "hidden" }}
            >
              <div
                data-testid="context-meter-bar"
                style={{ width: `${pct}%`, height: "100%", background: color, transition: "width 0.3s" }}
              />
            </div>
          )}
        </>
      )}

      {/* Per-chat running totals across every turn (tokens + wall-clock time), plus the average. */}
      {totals && totals.turns > 0 && (
        <div
          data-testid="chat-totals"
          style={{ marginTop: 4, paddingTop: 4, borderTop: "1px solid rgba(127,127,127,0.2)" }}
        >
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span style={{ color: "#888" }}>
              Chat total · {totals.turns} {totals.turns === 1 ? "turn" : "turns"}
            </span>
            <span>
              {fmt(totals.tokens)} tokens · {fmtMs(totals.ms)}
            </span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", color: "#aaa" }}>
            <span>avg / turn</span>
            <span>
              {fmt(Math.round(totals.tokens / totals.turns))} tokens · {fmtMs(totals.ms / totals.turns)}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
