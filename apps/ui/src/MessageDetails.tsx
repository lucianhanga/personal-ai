import { useEffect, useRef, useState } from "react";

import { AGENT_BG, AGENT_FG } from "./agentColors";
import { blockedEgressHost, type ToolStep, type TraceItem } from "./api";
import { ToolIO } from "./ToolIO";

// Color code for the agent-flow trace (no emoji, per project convention): shared per-agent hues
// (so the Agents config matches), plus tool violet and green/red for results + verification.
const TRACE = {
  planner: AGENT_FG.planner,
  researcher: AGENT_FG.researcher,
  tool: "#7c3aed", // violet
  critic: AGENT_FG.critic,
  ok: "#1a7f37", // green
  err: "#b00020", // red
  retrieval: "#1558b0", // royal indigo — matches the Activity-pane retrieval chip (#462)
  warn: "#b06f00", // amber — in-progress retrieval
} as const;

// Friendly labels for the multi-source fan-out's source kinds (#462), so the chat-side retrieval
// line reads "Documents, Memory" rather than the internal "vector, memory".
const SOURCE_LABEL: Record<string, string> = {
  vector: "Documents",
  memory: "Memory",
  graph: "Knowledge graph",
};
function sourceLabel(name: string): string {
  return SOURCE_LABEL[name] ?? name.charAt(0).toUpperCase() + name.slice(1);
}

// Very faded per-agent backgrounds so each contributor's lines are easy to delimit in the trace.
const TRACE_BG: Record<string, string> = {
  reasoning: AGENT_BG.researcher,
  plan: AGENT_BG.planner,
  critique: AGENT_BG.critic,
  tool_call: "#f6f0fe", // tool (violet)
  tool_result: "#f6f0fe",
  verification: AGENT_BG.planner,
  draft: "#fff7d6", // a highlighter-style tint so the proposed (draft) answer stands out (#393)
  retrieval: "#eef4fc", // faint indigo wash for the context-retrieval line (#462)
};

function rowStyle(kind: string, extra?: React.CSSProperties): React.CSSProperties {
  return {
    background: TRACE_BG[kind] ?? "transparent",
    borderRadius: 3,
    padding: "1px 5px",
    margin: "1px 0",
    whiteSpace: "pre-wrap",
    ...extra,
  };
}

/** A small bold, colored agent/step label that prefixes each trace line. */
function Tag({ color, children }: { color: string; children: React.ReactNode }): React.ReactElement {
  return <span style={{ color, fontWeight: 600 }}>{children}</span>;
}

// The researcher produces these step kinds; a new researcher block starts when one of them follows
// another agent's step (planner/critic/verifier). Used to label the researcher's block like the
// other agents (it only appears in the multi-agent graph, where those boundary steps exist).
const RESEARCHER_KINDS = new Set(["reasoning", "tool_call", "tool_result", "draft"]);
// `retrieval` (#462) is a boundary too: the gather node's context-assembly line sits between the
// planner's plan and the researcher's first step, so a researcher block that follows it still gets
// its "Researcher" header.
const AGENT_BLOCK_KINDS = new Set(["plan", "critique", "verification", "retrieval"]);

/** Insert a synthetic "researcher header" marker before each researcher block (multi-agent only). */
function withResearcherHeaders(items: TraceItem[]): (TraceItem | { kind: "researcher_header" })[] {
  const out: (TraceItem | { kind: "researcher_header" })[] = [];
  items.forEach((t, k) => {
    if (RESEARCHER_KINDS.has(t.kind) && k > 0 && AGENT_BLOCK_KINDS.has(items[k - 1].kind)) {
      out.push({ kind: "researcher_header" });
    }
    out.push(t);
  });
  return out;
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
  onAllowHost,
}: {
  trace?: TraceItem[];
  steps?: ToolStep[];
  thinking?: string | null;
  defaultOpen?: boolean;
  // Called when the user allows a host an egress-blocked tool tried to reach (allow-on-deny).
  onAllowHost?: (host: string) => void;
}): React.ReactElement | null {
  const [open, setOpen] = useState(defaultOpen);
  const [allowed, setAllowed] = useState<Set<string>>(new Set());
  const bodyRef = useRef<HTMLDivElement>(null);
  // Follow the stream only while the user is at the bottom; once they scroll up to read an earlier
  // step, leave them there (don't yank back down) and offer a "jump to latest" affordance.
  const stick = useRef(true);
  const [atBottom, setAtBottom] = useState(true);
  const items = trace?.length ? trace : legacyTrace(steps, thinking);

  function onBodyScroll(): void {
    const el = bodyRef.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    stick.current = near;
    setAtBottom(near);
  }
  function jumpToLatest(): void {
    const el = bodyRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    stick.current = true;
    setAtBottom(true);
  }

  // Opening the panel jumps to the latest.
  useEffect(() => {
    if (open && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
      stick.current = true;
      setAtBottom(true);
    }
  }, [open]);
  // While streaming, follow new content only if the user is still at the bottom.
  useEffect(() => {
    if (open && stick.current && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [items, open]);

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
    <div data-testid="msg-details" style={{ fontSize: "0.85rem", margin: "0.2rem 0" }}>
      <button
        data-testid="details-toggle"
        onClick={() => setOpen((o) => !o)}
        style={{ background: "none", border: "none", color: "#666", cursor: "pointer", padding: 0 }}
      >
        {open ? "▾" : "▸"} Details{summary ? ` · ${summary}` : ""}
      </button>
      {open && (
        <div style={{ position: "relative" }}>
          {!atBottom && (
            <button
              data-testid="details-jump"
              onClick={jumpToLatest}
              style={{
                position: "absolute",
                right: "0.5rem",
                bottom: "0.4rem",
                fontSize: "0.72rem",
                background: "#eef",
                color: "#338",
                border: "1px solid #bcd",
                borderRadius: "1rem",
                padding: "0.1rem 0.55rem",
                cursor: "pointer",
              }}
            >
              ▾ latest
            </button>
          )}
          <div
            data-testid="details-body"
            ref={bodyRef}
            onScroll={onBodyScroll}
            style={{
              marginTop: "0.3rem",
              paddingLeft: "0.6rem",
              borderLeft: "2px solid rgba(127,127,127,0.3)",
              color: "#555",
              // Running window (~20 lines); scroll inside to read the full reasoning.
              maxHeight: "20em",
              overflowY: "auto",
            }}
          >
          {(() => {
            const rows = withResearcherHeaders(items);
            // tool_call rows render one <ToolIO> that absorbs their paired tool_result; mark the
            // consumed result so the look-behind below skips re-rendering it as its own row.
            const consumed = new Set<number>();
            // The last `draft` is the current proposal; earlier ones were superseded by a revise
            // loop and render dimmed (#393).
            let lastDraftIdx = -1;
            for (let j = rows.length - 1; j >= 0; j--) {
              if (rows[j].kind === "draft") {
                lastDraftIdx = j;
                break;
              }
            }
            return rows.map((t, k) => {
            if (consumed.has(k)) return null;
            if (t.kind === "researcher_header") {
              return (
                <div key={k} data-testid="details-researcher" style={rowStyle("reasoning")}>
                  <Tag color={TRACE.researcher}>Researcher</Tag>
                </div>
              );
            }
            if (t.kind === "reasoning") {
              return (
                <div key={k} data-testid="details-thinking" style={rowStyle("reasoning")}>
                  <Tag color={TRACE.researcher}>Thinking</Tag> {t.text}
                </div>
              );
            }
            if (t.kind === "tool_call") {
              // Look ahead for the next tool_result for the same tool and fold it into one ToolIO,
              // so a call + its result read as a single progressive-disclosure interaction.
              let result: TraceItem | undefined;
              for (let j = k + 1; j < rows.length; j++) {
                const r = rows[j];
                if ("kind" in r && r.kind === "tool_result" && (r.tool == null || r.tool === t.tool)) {
                  result = r;
                  consumed.add(j);
                  break;
                }
              }
              const host = result && !result.ok ? blockedEgressHost(result.error) : null;
              return (
                <ToolIO
                  key={k}
                  tool={t.tool ?? "tool"}
                  args={t.args ?? {}}
                  ok={result ? result.ok ?? false : undefined}
                  output={result?.output}
                  error={result?.error}
                  host={host}
                  allowed={host ? allowed.has(host) : false}
                  onAllow={
                    host && onAllowHost
                      ? () => {
                          setAllowed((a) => new Set(a).add(host));
                          onAllowHost(host);
                        }
                      : undefined
                  }
                />
              );
            }
            if (t.kind === "tool_result") {
              // An orphan result (no preceding call, e.g. legacy/partial trace) still renders via ToolIO.
              const host = t.ok ? null : blockedEgressHost(t.error);
              return (
                <ToolIO
                  key={k}
                  tool={t.tool ?? "tool"}
                  ok={t.ok ?? false}
                  output={t.output}
                  error={t.error}
                  host={host}
                  allowed={host ? allowed.has(host) : false}
                  onAllow={
                    host && onAllowHost
                      ? () => {
                          setAllowed((a) => new Set(a).add(host));
                          onAllowHost(host);
                        }
                      : undefined
                  }
                />
              );
            }
            if (t.kind === "plan") {
              return (
                <div key={k} data-testid="details-plan" style={rowStyle("plan")}>
                  <Tag color={TRACE.planner}>Planner</Tag>: {t.text}
                </div>
              );
            }
            if (t.kind === "critique") {
              return (
                <div key={k} data-testid="details-critique" style={rowStyle("critique")}>
                  <Tag color={TRACE.critic}>Critic</Tag>
                  {t.role ? ` (${t.role})` : ""}: {t.text}
                </div>
              );
            }
            if (t.kind === "draft") {
              // The researcher's proposed answer, highlighted in the reasoning pane (#393). The
              // accepted answer is written to the output bubble by finalize; superseded drafts dim.
              const superseded = k !== lastDraftIdx;
              const label = `Draft answer${t.attempt && t.attempt > 1 ? ` · attempt ${t.attempt}` : ""}`;
              return (
                <div
                  key={k}
                  data-testid="details-draft"
                  style={rowStyle("draft", {
                    borderLeft: `3px solid ${TRACE.researcher}`,
                    opacity: superseded ? 0.5 : 1,
                  })}
                >
                  <Tag color={TRACE.researcher}>{label}</Tag>
                  {superseded ? " (superseded)" : ""}
                  {t.text ? `: ${t.text}` : ""}
                </div>
              );
            }
            if (t.kind === "verification") {
              const pass = t.verdict === "pass";
              return (
                <div
                  key={k}
                  data-testid="details-verification"
                  style={rowStyle("verification", { color: pass ? TRACE.ok : TRACE.err })}
                >
                  <Tag color={pass ? TRACE.ok : TRACE.err}>
                    Verify{t.verdict ? ` (${t.verdict})` : ""}
                  </Tag>
                  {t.text ? `: ${t.text}` : ""}
                </div>
              );
            }
            if (t.kind === "stage") {
              // Generic stage heartbeat (#465): a transient amber "working" row (Planning… /
              // Selecting sources… / Researching… / Reviewing… / Finalizing…) so a busy or
              // model-waiting node never reads as blocked. Cleared when the turn settles.
              return (
                <div
                  key={k}
                  data-testid="details-stage"
                  style={rowStyle("stage", { color: TRACE.warn })}
                >
                  <Tag color={TRACE.warn}>Working</Tag>: {t.label ?? "In progress"}…
                </div>
              );
            }
            if (t.kind === "retrieval") {
              // Live retrieval progress (#462): the gather node's running -> done frame during the
              // planner->researcher gap, shown here so the chat transcript (not just the Activity
              // pane) reflects context being assembled. Running shows an amber "Retrieving…" line;
              // done settles to the hit count. Persisted per-source items (with `source_kind`) also
              // land here on reload and render their own labelled count.
              const running = t.status === "running";
              const n = t.hits ?? 0;
              const srcs = (t.sources ?? []).map(sourceLabel).filter(Boolean).join(", ");
              const label = running
                ? srcs
                  ? `Retrieving context from ${srcs}…`
                  : "Retrieving context…"
                : t.source_kind
                  ? `Retrieved ${n} passage${n === 1 ? "" : "s"} (${sourceLabel(t.source_kind)})`
                  : `Retrieved ${n} passage${n === 1 ? "" : "s"}`;
              return (
                <div
                  key={k}
                  data-testid="details-retrieval"
                  style={rowStyle("retrieval", { color: running ? TRACE.warn : undefined })}
                >
                  <Tag color={running ? TRACE.warn : TRACE.retrieval}>Context</Tag>: {label}
                </div>
              );
            }
            // Generic fallback so any future trace kind renders instead of breaking the UI.
            return (
              <div key={k} data-testid="details-other" style={rowStyle(t.kind)}>
                <Tag color={TRACE.researcher}>{t.kind}</Tag>
                {t.text ? `: ${t.text}` : ""}
              </div>
            );
            });
          })()}
          </div>
        </div>
      )}
    </div>
  );
}
