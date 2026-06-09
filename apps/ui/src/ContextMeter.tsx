import type { UsageInfo } from "./api";

const fmt = (n: number): string => n.toLocaleString();

/** Visualize how full the model's context window is after a turn (token usage). */
export function ContextMeter({ usage }: { usage: UsageInfo }): React.ReactElement {
  const prompt = usage.prompt_tokens ?? 0;
  const limit = usage.context_limit ?? null;
  const pct = limit ? Math.min(100, Math.round((prompt / limit) * 100)) : null;
  // Green under 70%, amber under 90%, red at/over 90%.
  const color = pct === null ? "#4a90d9" : pct < 70 ? "#2a9d4a" : pct < 90 ? "#b06f00" : "#b00";

  return (
    <div
      data-testid="context-meter"
      title="Context window usage for the last turn"
      style={{ fontSize: "0.72rem", color: "#555", margin: "0.25rem 0" }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
        <span>Context</span>
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
    </div>
  );
}
