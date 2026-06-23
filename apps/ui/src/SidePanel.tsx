import type { Dispatch, SetStateAction } from "react";

import type { ContextBreakdown, UsageInfo } from "./api";
import { AppLogs } from "./AppLogs";
import { ContextMeter } from "./ContextMeter";
import { ToolLog } from "./ToolLog";

interface SidePanelProps {
  token: string;
  conversationId: string | null;
  usage: UsageInfo | null;
  totals: { tokens: number; ms: number; turns: number };
  context: ContextBreakdown | null;
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
  usage,
  totals,
  context,
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

      {(context || usage) && <ContextMeter usage={usage} totals={totals} context={context} />}

      {showLog && <ToolLog token={token} conversationId={conversationId} />}
      {showAppLogs && <AppLogs token={token} conversationId={conversationId} />}

      {!showLog && !showAppLogs && !context && !usage && (
        <p data-testid="side-hint" style={{ color: "#888", fontSize: "0.8rem" }}>
          Open a panel above to view activity or app logs; the context appears here as you chat.
        </p>
      )}
    </aside>
  );
}
