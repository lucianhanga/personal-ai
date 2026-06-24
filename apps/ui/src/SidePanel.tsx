import type { Dispatch, SetStateAction } from "react";

import type { ChatMessage, ContextBreakdown, TraceItem, UsageInfo } from "./api";
import { ActivityTimeline } from "./ActivityTimeline";
import { AppLogs } from "./AppLogs";
import { ContextMeter } from "./ContextMeter";
import { ToolLog } from "./ToolLog";

interface SidePanelProps {
  token: string;
  conversationId: string | null;
  messages: ChatMessage[];
  trace: Record<number, TraceItem[]>;
  usage: UsageInfo | null;
  totals: { tokens: number; ms: number; turns: number };
  context: ContextBreakdown | null;
  busy: boolean;
  onAllowHost?: (host: string) => void;
  collapsed: boolean;
  setCollapsed: Dispatch<SetStateAction<boolean>>;
  showLog: boolean;
  setShowLog: Dispatch<SetStateAction<boolean>>;
  showAppLogs: boolean;
  setShowAppLogs: Dispatch<SetStateAction<boolean>>;
}

/** Right column: collapsible activity / app-logs / context panels. */
export function SidePanel({
  token,
  conversationId,
  messages,
  trace,
  usage,
  totals,
  context,
  busy,
  onAllowHost,
  collapsed,
  setCollapsed,
  showLog,
  setShowLog,
  showAppLogs,
  setShowAppLogs,
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
      <div style={{ display: "flex", gap: "0.4rem", alignItems: "center", flexWrap: "wrap" }}>
        <button data-testid="toollog-show" onClick={() => setShowLog((v) => !v)}>
          {showLog ? "Hide activity" : "Activity"}
        </button>
        <button data-testid="applogs-show" onClick={() => setShowAppLogs((v) => !v)}>
          {showAppLogs ? "Hide app logs" : "App logs"}
        </button>
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
          timeline's newest turn, so pass context={null} here to avoid duplicating it. */}
      {usage && <ContextMeter usage={usage} totals={totals} context={null} />}

      {/* The centerpiece: a unified, reverse-chronological activity timeline (context + tools +
          reasoning) per question. Raw logs below stay available as a complementary view. */}
      <ActivityTimeline
        messages={messages}
        trace={trace}
        liveContext={context}
        liveUsage={usage}
        busy={busy}
        onAllowHost={onAllowHost}
      />

      {showLog && <ToolLog token={token} conversationId={conversationId} />}
      {showAppLogs && <AppLogs token={token} conversationId={conversationId} />}
    </aside>
  );
}
