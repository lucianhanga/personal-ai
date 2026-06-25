import type { Dispatch, SetStateAction } from "react";

import type { ChatMessage, ContextBreakdown, TraceItem, UsageInfo } from "./api";
import { ActivityTimeline, type LiveActivity } from "./ActivityTimeline";
import { ContextMeter } from "./ContextMeter";

interface SidePanelProps {
  messages: ChatMessage[];
  trace: Record<number, TraceItem[]>;
  usage: UsageInfo | null;
  totals: { tokens: number; ms: number; turns: number };
  contexts: Record<number, ContextBreakdown>;
  busy: boolean;
  onAllowHost?: (host: string) => void;
  collapsed: boolean;
  setCollapsed: Dispatch<SetStateAction<boolean>>;
  // Pre-turn resource activities being processed in the composer (#424); threaded to the timeline.
  liveActivities?: LiveActivity[];
}

/** Right column: the collapsible Activity pane (per-turn timeline + live context meter). */
export function SidePanel({
  messages,
  trace,
  usage,
  totals,
  contexts,
  busy,
  onAllowHost,
  collapsed,
  setCollapsed,
  liveActivities = [],
}: SidePanelProps): React.ReactElement {
  if (collapsed) {
    return (
      <button
        data-testid="side-toggle"
        onClick={() => setCollapsed(false)}
        title="Show panels"
        style={{ flex: "0 0 auto", alignSelf: "flex-start" }}
      >
        ‹ Panels
      </button>
    );
  }
  return (
    <aside
      data-testid="side-panel"
      aria-label="panels"
      style={{ flex: 2, minWidth: 0, display: "flex", flexDirection: "column", gap: "0.5rem" }}
    >
      {/* Panel header: title (left) + collapse control (right), with a subtle bottom divider. */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.4rem",
          paddingBottom: "0.4rem",
          borderBottom: "1px solid rgba(127,127,127,0.2)",
        }}
      >
        <strong style={{ fontSize: "0.9rem" }}>Activity</strong>
        <button
          data-testid="side-toggle"
          onClick={() => setCollapsed(true)}
          title="Collapse panel"
          style={{ marginLeft: "auto" }}
        >
          Collapse ›
        </button>
      </div>

      {/* Live window-usage + chat totals only — the per-turn context composition now lives in the
          timeline's per-turn nodes, so pass context={null} here to avoid duplicating it. */}
      {usage && <ContextMeter usage={usage} totals={totals} context={null} />}

      {/* The centerpiece: a unified, reverse-chronological activity timeline (context + tools +
          reasoning) per question — the full history of the conversation. */}
      <ActivityTimeline
        messages={messages}
        trace={trace}
        contexts={contexts}
        liveUsage={usage}
        busy={busy}
        onAllowHost={onAllowHost}
        liveActivities={liveActivities}
      />
    </aside>
  );
}
