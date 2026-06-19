import type { ContextBreakdown, UsageInfo } from "./api";

const fmt = (n: number): string => n.toLocaleString();
// Rough token estimate from characters (~4 chars/token) for the per-component composition view.
const approxTokens = (chars: number): number => Math.max(1, Math.round(chars / 4));

const BAR = "#4a90d9";

/** Show what's in the model's context this turn (composition) and how full the window is (usage). */
export function ContextMeter({
  usage,
  context,
}: {
  usage: UsageInfo | null;
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
      <div style={{ fontWeight: 600, marginBottom: 3 }}>Context</div>

      {/* Composition: what was assembled into the prompt this turn (shown as the question is asked). */}
      {context && context.items.length > 0 && (
        <div data-testid="context-breakdown" style={{ marginBottom: usage ? "0.4rem" : 0 }}>
          {context.items.map((it) => {
            const share = context.total_chars
              ? Math.round((it.chars / context.total_chars) * 100)
              : 0;
            return (
              <div key={it.label} data-testid="context-item" style={{ marginBottom: 3 }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span>
                    {it.label}
                    {it.count > 1 ? ` (${it.count})` : ""}
                  </span>
                  <span style={{ color: "#888" }}>~{fmt(approxTokens(it.chars))} tok</span>
                </div>
                <div style={{ height: 4, borderRadius: 3, background: "rgba(127,127,127,0.15)" }}>
                  <div style={{ width: `${share}%`, height: "100%", background: BAR, borderRadius: 3 }} />
                </div>
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
    </div>
  );
}
