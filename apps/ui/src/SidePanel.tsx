import type { Dispatch, SetStateAction } from "react";

import type { UsageInfo } from "./api";
import { AppLogs } from "./AppLogs";
import { ContextMeter } from "./ContextMeter";
import { McpActivity } from "./McpActivity";
import { ToolLog } from "./ToolLog";

interface SidePanelProps {
  token: string;
  conversationId: string | null;
  usage: UsageInfo | null;
  collapsed: boolean;
  setCollapsed: Dispatch<SetStateAction<boolean>>;
  showLog: boolean;
  setShowLog: Dispatch<SetStateAction<boolean>>;
  showAppLogs: boolean;
  setShowAppLogs: Dispatch<SetStateAction<boolean>>;
  showMcpActivity: boolean;
  setShowMcpActivity: Dispatch<SetStateAction<boolean>>;
}

/** Right column: collapsible logs / MCP activity / context-usage panels. */
export function SidePanel({
  token,
  conversationId,
  usage,
  collapsed,
  setCollapsed,
  showLog,
  setShowLog,
  showAppLogs,
  setShowAppLogs,
  showMcpActivity,
  setShowMcpActivity,
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
        <button data-testid="mcp-activity-show" onClick={() => setShowMcpActivity((v) => !v)}>
          {showMcpActivity ? "Hide MCP" : "MCP"}
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

      {usage && <ContextMeter usage={usage} />}

      {showLog && <ToolLog token={token} conversationId={conversationId} />}
      {showAppLogs && <AppLogs token={token} conversationId={conversationId} />}
      {showMcpActivity && <McpActivity token={token} />}

      {!showLog && !showAppLogs && !showMcpActivity && !usage && (
        <p data-testid="side-hint" style={{ color: "#888", fontSize: "0.8rem" }}>
          Open a panel above to view logs, MCP activity, or context usage.
        </p>
      )}
    </aside>
  );
}
