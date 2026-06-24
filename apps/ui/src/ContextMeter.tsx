import type { ContextBreakdown, UsageInfo } from "./api";
import { ContextComposition } from "./ContextComposition";

const fmt = (n: number): string => n.toLocaleString();
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

  return (
    <div
      data-testid="context-meter"
      style={{ fontSize: "0.72rem", color: "#555", margin: "0.25rem 0" }}
    >
      {/* Composition: what was assembled into the prompt this turn (shown as the question is asked). */}
      {context && (
        <div style={{ marginBottom: usage && context.items.length > 0 ? "0.4rem" : 0 }}>
          <ContextComposition
            context={context}
            collapsible
            defaultOpen
            storageKey="personalai_context_open"
          />
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
