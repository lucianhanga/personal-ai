import { useEffect, useState } from "react";

import type { ContextBreakdown } from "./api";

// Alternating tints so adjacent token boundaries are visible (playground-style).
const TOKEN_TINT_A = "rgba(74,144,217,0.14)";
const TOKEN_TINT_B = "rgba(127,127,127,0.12)";

/**
 * Render a source's text as the actual token PIECES it splits into (#391). The tokenizer is an
 * APPROXIMATE, in-browser GPT-style BPE (o200k_base) — boundaries won't exactly match a local
 * model, hence the honest "approx" label. Bounded + lazy (only mounted when the token view is on).
 */
function TokenChips({ text }: { text: string }): React.ReactElement {
  // Lazy-load the tokenizer (its o200k vocab is ~2 MB) only when a token view is actually opened,
  // so it stays out of the main bundle (#391); `null` while it loads.
  const [pieces, setPieces] = useState<string[] | null>(null);
  useEffect(() => {
    let active = true;
    void import("gpt-tokenizer/encoding/o200k_base").then(({ encode, decode }) => {
      if (active) setPieces(encode(text).map((id) => decode([id])));
    });
    return () => {
      active = false;
    };
  }, [text]);
  return (
    <div
      data-testid="context-tokens"
      style={{
        maxHeight: "14em",
        overflow: "auto",
        marginTop: 3,
        padding: "0.3rem 0.4rem",
        background: "rgba(127,127,127,0.06)",
        borderRadius: 4,
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        fontSize: "0.72rem",
        lineHeight: 1.7,
      }}
    >
      <div style={{ color: "#6b7280", marginBottom: 4 }}>
        {pieces === null
          ? "tokenizing…"
          : `${pieces.length.toLocaleString()} tokens · approx (GPT-style)`}
      </div>
      {pieces !== null && (
        <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {pieces.map((p, i) => (
            <span
              key={i}
              style={{ background: i % 2 ? TOKEN_TINT_B : TOKEN_TINT_A, borderRadius: 2 }}
            >
              {p}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// Plain-language, one-sentence explanations per composition source, keyed by a normalized (trimmed,
// lowercased) label. The keys match the labels the backend actually emits for each context source.
// Falls back to a generic line for any source we don't have copy for yet.
const EXPLANATIONS: Record<string, string> = {
  "current date/time":
    "Today's date and time, so answers aren't anchored to the model's training cutoff.",
  grounding: "An instruction to answer from the provided context and not fabricate facts.",
  "interpreted request": "The assistant's restatement of what you asked, to keep it on track.",
  "reasoning hint": "A nudge on how much to deliberate before answering.",
  documents: "Passages retrieved from files you uploaded, matched to your question.",
  memory: "Facts saved from past chats that the assistant is allowed to recall.",
  "conversation + your message": "Earlier turns in this chat plus your current message.",
};
const GENERIC_EXPL = "Included in the prompt for this turn.";

export function explain(label: string): string {
  return EXPLANATIONS[label.trim().toLowerCase()] ?? GENERIC_EXPL;
}

const fmt = (n: number): string => n.toLocaleString();
// Rough token estimate from characters (~4 chars/token) for the per-component composition view.
export const approxTokens = (chars: number): number => Math.max(1, Math.round(chars / 4));

const BAR = "#4a90d9";

/**
 * The "Context" composition block: per-source rows (label, count, ~token estimate, share bar, and a
 * keyboard/tap explanation popover) plus the "Assembled ~N tokens" footer. Reused by the live
 * ContextMeter and by each past assistant message's collapsed context-history disclosure.
 *
 * `collapsible` adds a header toggle (persisted under `storageKey`, default open via `defaultOpen`).
 * `idPrefix` namespaces the localStorage key so two instances on one page don't collide.
 */
export function ContextComposition({
  context,
  collapsible = false,
  defaultOpen = true,
  storageKey,
  idPrefix = "ctx",
}: {
  context: ContextBreakdown;
  collapsible?: boolean;
  defaultOpen?: boolean;
  storageKey?: string;
  idPrefix?: string;
}): React.ReactElement | null {
  // Which composition row's token overlay is showing (on hover).
  const [hovered, setHovered] = useState<string | null>(null);
  // Collapsible section state; persisted under storageKey so the choice survives reloads.
  const [open, setOpen] = useState<boolean>(() => {
    if (!collapsible) return true;
    if (!storageKey) return defaultOpen;
    try {
      const v = localStorage.getItem(storageKey);
      return v === null ? defaultOpen : v !== "0";
    } catch {
      return defaultOpen;
    }
  });
  // Which row's plain-language explanation popover is open (keyboard/tap toggle, AA-readable).
  const [expl, setExpl] = useState<string | null>(null);
  // Whether the token view is shown: each source's text rendered as the actual token pieces (#391).
  // Hidden by default for a cleaner breakdown; one toggle governs the whole composition.
  const [showTokens, setShowTokens] = useState<boolean>(false);

  function toggleOpen(): void {
    setOpen((o) => {
      const next = !o;
      if (storageKey) {
        try {
          localStorage.setItem(storageKey, next ? "1" : "0");
        } catch {
          // Storage unavailable (private mode / blocked) — state still works for the session.
        }
      }
      return next;
    });
  }

  if (context.items.length === 0) return null;

  return (
    <>
      {/* Collapsible header: toggles the composition breakdown; choice persists in localStorage. */}
      {collapsible && (
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
      )}

      {/* Composition: what was assembled into the prompt for this question. */}
      {open && (
        <div data-testid="context-breakdown">
          {context.items.map((it, idx) => {
            const share = context.total_chars
              ? Math.round((it.chars / context.total_chars) * 100)
              : 0;
            const tokens = approxTokens(it.chars);
            const explId = `${idPrefix}-${it.label}`;
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
                    {/* One global token toggle for the whole composition, anchored to the first
                        row's controls so it's discoverable next to the `?` button. */}
                    {idx === 0 && (
                      <button
                        data-testid="context-tokens-toggle"
                        type="button"
                        tabIndex={0}
                        aria-pressed={showTokens}
                        title={showTokens ? "Hide tokens" : "Show tokens"}
                        aria-label={showTokens ? "Hide tokens" : "Show tokens"}
                        onClick={(e) => {
                          e.stopPropagation();
                          setShowTokens((s) => !s);
                        }}
                        style={{
                          width: 14,
                          height: 14,
                          lineHeight: "12px",
                          fontSize: "0.62rem",
                          borderRadius: "50%",
                          border: "1px solid rgba(127,127,127,0.5)",
                          background: showTokens ? "rgba(74,144,217,0.15)" : "none",
                          color: showTokens ? "#4a90d9" : "#6b7280",
                          cursor: "pointer",
                          padding: 0,
                        }}
                      >
                        #
                      </button>
                    )}
                  </span>
                  {showTokens && (
                    <span style={{ color: "#888" }} title="character-based estimate">
                      ~{fmt(tokens)} tok
                    </span>
                  )}
                </div>
                {expl === it.label && (
                  <div
                    data-testid="context-expl"
                    id={explId}
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
                {/* The actual token pieces of this source's text (#391) — only when the token view
                    is on and the source carries text (absent on pre-#391 persisted turns). */}
                {showTokens && it.text ? <TokenChips text={it.text} /> : null}
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
          {showTokens && (
            <div style={{ color: "#888", marginTop: 2 }}>
              Assembled ~{fmt(approxTokens(context.total_chars))} tokens (estimate)
            </div>
          )}
        </div>
      )}
    </>
  );
}
