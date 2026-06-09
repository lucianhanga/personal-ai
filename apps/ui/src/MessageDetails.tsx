import { useState } from "react";

import type { ToolStep } from "./api";

/**
 * Collapsible per-message detail (ChatGPT-style): the tool calls the model made and its reasoning.
 * Lives with the assistant message, so it survives chat switches and conversation reloads.
 */
export function MessageDetails({
  steps,
  thinking,
  defaultOpen = false,
}: {
  steps?: ToolStep[];
  thinking?: string | null;
  defaultOpen?: boolean;
}): React.ReactElement | null {
  const [open, setOpen] = useState(defaultOpen);
  const calls = (steps ?? []).filter((s) => s.phase === "call").length;
  if (!steps?.length && !thinking) return null;

  const summary = [
    calls ? `${calls} tool call${calls > 1 ? "s" : ""}` : null,
    thinking ? "reasoning" : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div data-testid="msg-details" style={{ fontSize: "0.75rem", margin: "0.2rem 0" }}>
      <button
        data-testid="details-toggle"
        onClick={() => setOpen((o) => !o)}
        style={{
          background: "none",
          border: "none",
          color: "#666",
          cursor: "pointer",
          padding: 0,
        }}
      >
        {open ? "▾" : "▸"} Details{summary ? ` · ${summary}` : ""}
      </button>
      {open && (
        <div
          data-testid="details-body"
          style={{
            marginTop: "0.3rem",
            paddingLeft: "0.6rem",
            borderLeft: "2px solid rgba(127,127,127,0.3)",
            color: "#555",
          }}
        >
          {thinking && (
            <div data-testid="details-thinking" style={{ whiteSpace: "pre-wrap", marginBottom: 4 }}>
              💭 {thinking}
            </div>
          )}
          {steps?.map((s, k) =>
            s.phase === "call" ? (
              <div key={k}>
                🔧 {s.tool}({JSON.stringify(s.args ?? {})})
              </div>
            ) : (
              <div key={k} style={{ color: s.ok ? "#2a7" : "#b00" }}>
                ↳ {s.tool}: {s.ok ? "ok" : `error: ${s.error}`}
              </div>
            ),
          )}
        </div>
      )}
    </div>
  );
}
