import { useEffect, useRef, useState } from "react";

import type { ToolStep, TraceItem } from "./api";

// Color code for the agent-flow trace (no emoji, per project convention): distinct hues per agent,
// and green=success / red=failure for results + verification.
const TRACE = {
  planner: "#2563eb", // blue
  researcher: "#6b7280", // gray (reasoning)
  tool: "#7c3aed", // violet
  critic: "#b8860b", // amber
  ok: "#1a7f37", // green
  err: "#b00020", // red
} as const;

/** A small bold, colored agent/step label that prefixes each trace line. */
function Tag({ color, children }: { color: string; children: React.ReactNode }): React.ReactElement {
  return <span style={{ color, fontWeight: 600 }}>{children}</span>;
}

/** Build an ordered trace from legacy (separate thinking + tool_steps) meta for old messages. */
function legacyTrace(steps?: ToolStep[], thinking?: string | null): TraceItem[] {
  const items: TraceItem[] = [];
  if (thinking) items.push({ kind: "reasoning", text: thinking });
  for (const s of steps ?? []) {
    items.push(
      s.phase === "call"
        ? { kind: "tool_call", tool: s.tool, args: s.args }
        : { kind: "tool_result", tool: s.tool, ok: s.ok, output: s.output, error: s.error },
    );
  }
  return items;
}

/**
 * Collapsible per-message detail (ChatGPT-style): the model's reasoning and tool calls, shown in
 * the order they actually happened. Survives chat switches + conversation reloads.
 */
export function MessageDetails({
  trace,
  steps,
  thinking,
  defaultOpen = false,
}: {
  trace?: TraceItem[];
  steps?: ToolStep[];
  thinking?: string | null;
  defaultOpen?: boolean;
}): React.ReactElement | null {
  const [open, setOpen] = useState(defaultOpen);
  const bodyRef = useRef<HTMLDivElement>(null);
  const items = trace?.length ? trace : legacyTrace(steps, thinking);

  // Keep the compact window following the latest reasoning/step while it streams.
  useEffect(() => {
    if (open && bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [open, items]);

  if (items.length === 0) return null;

  const calls = items.filter((t) => t.kind === "tool_call").length;
  const hasReasoning = items.some((t) => t.kind === "reasoning");
  const summary = [
    calls ? `${calls} tool call${calls > 1 ? "s" : ""}` : null,
    hasReasoning ? "reasoning" : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div data-testid="msg-details" style={{ fontSize: "0.75rem", margin: "0.2rem 0" }}>
      <button
        data-testid="details-toggle"
        onClick={() => setOpen((o) => !o)}
        style={{ background: "none", border: "none", color: "#666", cursor: "pointer", padding: 0 }}
      >
        {open ? "▾" : "▸"} Details{summary ? ` · ${summary}` : ""}
      </button>
      {open && (
        <div
          data-testid="details-body"
          ref={bodyRef}
          style={{
            marginTop: "0.3rem",
            paddingLeft: "0.6rem",
            borderLeft: "2px solid rgba(127,127,127,0.3)",
            color: "#555",
            // Compact running window (~5 lines); scroll inside to read the full reasoning.
            maxHeight: "7.5em",
            overflowY: "auto",
          }}
        >
          {items.map((t, k) => {
            if (t.kind === "reasoning") {
              return (
                <div
                  key={k}
                  data-testid="details-thinking"
                  style={{ whiteSpace: "pre-wrap", margin: "2px 0" }}
                >
                  <Tag color={TRACE.researcher}>Thinking</Tag> {t.text}
                </div>
              );
            }
            if (t.kind === "tool_call") {
              return (
                <div key={k}>
                  <Tag color={TRACE.tool}>Tool</Tag> {t.tool}({JSON.stringify(t.args ?? {})})
                </div>
              );
            }
            if (t.kind === "tool_result") {
              return (
                <div key={k} style={{ color: t.ok ? TRACE.ok : TRACE.err }}>
                  <Tag color={t.ok ? TRACE.ok : TRACE.err}>Result</Tag> {t.tool}:{" "}
                  {t.ok ? "ok" : `error: ${t.error}`}
                </div>
              );
            }
            if (t.kind === "plan") {
              return (
                <div key={k} data-testid="details-plan" style={{ whiteSpace: "pre-wrap" }}>
                  <Tag color={TRACE.planner}>Planner</Tag>: {t.text}
                </div>
              );
            }
            if (t.kind === "critique") {
              return (
                <div key={k} data-testid="details-critique" style={{ whiteSpace: "pre-wrap" }}>
                  <Tag color={TRACE.critic}>Critic</Tag>
                  {t.role ? ` (${t.role})` : ""}: {t.text}
                </div>
              );
            }
            if (t.kind === "verification") {
              const pass = t.verdict === "pass";
              return (
                <div
                  key={k}
                  data-testid="details-verification"
                  style={{ color: pass ? TRACE.ok : TRACE.err }}
                >
                  <Tag color={pass ? TRACE.ok : TRACE.err}>
                    Verify{t.verdict ? ` (${t.verdict})` : ""}
                  </Tag>
                  {t.text ? `: ${t.text}` : ""}
                </div>
              );
            }
            // Generic fallback so any future trace kind renders instead of breaking the UI.
            return (
              <div key={k} data-testid="details-other" style={{ whiteSpace: "pre-wrap" }}>
                <Tag color={TRACE.researcher}>{t.kind}</Tag>
                {t.text ? `: ${t.text}` : ""}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
