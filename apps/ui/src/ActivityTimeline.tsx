import { useState } from "react";

import { AGENT_FG } from "./agentColors";
import {
  blockedEgressHost,
  type ChatMessage,
  type ContextBreakdown,
  type TraceItem,
  type UsageInfo,
} from "./api";
import { approxTokens, ContextComposition } from "./ContextComposition";
import { ToolIO } from "./ToolIO";

// Color code shared with the in-transcript trace (MessageDetails) and the Agents config — no emoji.
const COLOR = {
  planner: AGENT_FG.planner, // blue
  researcher: AGENT_FG.researcher, // gray
  tool: "#7c3aed", // violet
  critic: AGENT_FG.critic, // amber
  ok: "#1a7f37", // green
  err: "#b00020", // red
  context: "#4a90d9", // accent blue
  live: "#b06f00", // amber (in-flight)
} as const;
// Muted text a user must READ uses #6b7280 (AA); #888/#999 stay decorative (matches the codebase).
const READABLE = "#6b7280";

// Milliseconds -> a short human duration; mirrors MessageList/ContextMeter so the timeline reads the
// same way as the rest of the UI (kept local to avoid a cross-module import for one helper).
const fmtMs = (ms: number): string =>
  ms < 1000
    ? `${Math.round(ms)} ms`
    : ms < 60000
      ? `${(ms / 1000).toFixed(1)} s`
      : `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
const compactTok = (n: number): string => (n >= 10000 ? `${(n / 1000).toFixed(1)}k` : n.toLocaleString());

// A coarse "Ns/Nm/Nh ago" from an ISO timestamp (absolute kept in the title for precision). "now" is
// the live, not-yet-persisted turn (no created_at).
function relTime(iso: string | undefined, now: number): string {
  if (!iso) return "just now";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

// Wall-clock time-of-day in UTC for a turn, e.g. "14:04:03Z" (the live turn uses the current time).
// Used as the per-turn fallback clock when a step has no per-step ts (older persisted turns).
function clockUTC(iso: string | undefined): string {
  const d = iso ? new Date(iso) : new Date();
  return Number.isNaN(d.getTime()) ? "" : `${d.toISOString().slice(11, 19)}Z`;
}

// Per-step UTC time from a trace item's `ts`; "" when absent/invalid so the caller can fall back to
// the turn clock. Each step now carries its OWN wall-clock time (backend stamps it as it happens).
function clockFromTs(iso: string | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : `${d.toISOString().slice(11, 19)}Z`;
}

// Which filter chips exist; "all" shows everything.
type Filter = "all" | "tools" | "reasoning" | "context";
const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "tools", label: "Tools" },
  { id: "reasoning", label: "Reasoning" },
  { id: "context", label: "Context" },
];

// A node's category, used for filtering and for the spine dot color.
type NodeKind = "context" | "tool" | "reasoning";

interface TurnNode {
  key: string;
  kind: NodeKind;
  dot: string; // spine dot color
  render: () => React.ReactElement;
}

interface Turn {
  index: number; // the assistant message index (also the React key + idPrefix seed)
  question: string;
  nodes: TurnNode[];
  toolCalls: number;
  tokens: number | null;
  elapsedMs: number | null;
  createdAt: string | undefined;
  isLive: boolean; // the in-flight turn (no usage yet + busy)
  status: string; // spine status-dot color (ok / err / tool / live)
}

function visibleNodes(nodes: TurnNode[], filter: Filter): TurnNode[] {
  if (filter === "all") return nodes;
  if (filter === "tools") return nodes.filter((n) => n.kind === "tool");
  if (filter === "reasoning") return nodes.filter((n) => n.kind === "reasoning");
  return nodes.filter((n) => n.kind === "context"); // context
}

/**
 * A unified, reverse-chronological "Activity timeline" for the side panel: one collapsible group per
 * question/answer turn (newest on top), each expanding to a vertical spine of that turn's events —
 * the assembled context, paired tool interactions (ToolIO), and the planner/researcher/critic/verify
 * reasoning — reusing the same components and color code as the in-transcript disclosures.
 */
export function ActivityTimeline({
  messages,
  trace,
  liveContext,
  liveUsage,
  busy,
  onAllowHost,
}: {
  messages: ChatMessage[];
  trace: Record<number, TraceItem[]>;
  liveContext: ContextBreakdown | null;
  liveUsage: UsageInfo | null;
  busy: boolean;
  onAllowHost?: (host: string) => void;
}): React.ReactElement {
  const [filter, setFilter] = useState<Filter>("all");
  // Per-turn open/closed overrides (keyed by message index); falls back to the default-open rule.
  const [overrides, setOverrides] = useState<Record<number, boolean>>({});
  // Hosts the user has allowed via an egress-blocked ToolIO this session (mirrors MessageDetails).
  const [allowed, setAllowed] = useState<Set<string>>(new Set());

  const lastAssistantIndex = (() => {
    for (let i = messages.length - 1; i >= 0; i--) if (messages[i].role === "assistant") return i;
    return -1;
  })();
  const now = Date.now();

  function allowHost(host: string): void {
    setAllowed((a) => new Set(a).add(host));
    onAllowHost?.(host);
  }

  // Build a ToolIO node from a tool_call (folding in its paired tool_result), matching MessageDetails.
  function toolNode(idx: number, k: number, call: TraceItem, result: TraceItem | undefined, time: string): TurnNode {
    const host = result && !result.ok ? blockedEgressHost(result.error) : null;
    return {
      key: `tl-${idx}-tool-${k}`,
      kind: "tool",
      dot: COLOR.tool,
      render: () => (
        <div>
          {time && (
            <div style={{ color: "#999", fontSize: "0.66rem", marginBottom: 1 }}>{time}</div>
          )}
          <ToolIO
            tool={call.tool ?? "tool"}
            args={call.args ?? {}}
            ok={result ? result.ok ?? false : undefined}
            output={result?.output}
            error={result?.error}
            host={host}
            allowed={host ? allowed.has(host) : false}
            onAllow={host && onAllowHost ? () => allowHost(host) : undefined}
          />
        </div>
      ),
    };
  }

  // An agent marker node (planner/researcher/critic/verify): just the agent NAME + a small timestamp.
  // The reasoning prose itself is intentionally NOT shown here — the full text stays in the
  // transcript's per-message Details; the timeline is a compact "who acted, and when" log.
  function labelNode(
    idx: number,
    k: number,
    color: string,
    label: string,
    time: string,
    testid: string,
  ): TurnNode {
    return {
      key: `tl-${idx}-r-${k}`,
      kind: "reasoning",
      dot: color,
      render: () => (
        <div data-testid={testid} style={{ display: "flex", alignItems: "baseline", gap: "0.4rem" }}>
          <span style={{ color, fontWeight: 600 }}>{label}</span>
          {time && <span style={{ color: "#999", fontSize: "0.66rem" }}>{time}</span>}
        </div>
      ),
    };
  }

  function buildNodes(
    idx: number,
    items: TraceItem[],
    context: ContextBreakdown | null,
    time: string,
  ): TurnNode[] {
    const nodes: TurnNode[] = [];
    // 1. Context assembled — first event in the turn's chronology.
    if (context && context.items.length > 0) {
      nodes.push({
        key: `tl-${idx}-ctx`,
        kind: "context",
        dot: COLOR.context,
        render: () => (
          <div data-testid="timeline-context">
            <div style={{ color: COLOR.context, fontWeight: 600, marginBottom: 2 }}>
              Context assembled (~{approxTokens(context.total_chars).toLocaleString()} tokens)
            </div>
            <ContextComposition context={context} collapsible={false} idPrefix={`tl-${idx}`} />
          </div>
        ),
      });
    }
    // 2. Walk the trace in order, pairing tool_call + tool_result into one ToolIO.
    const consumed = new Set<number>();
    items.forEach((t, k) => {
      if (consumed.has(k)) return;
      // Each step's OWN wall-clock time (backend `ts`), falling back to the turn clock when absent.
      const stepTime = clockFromTs(t.ts) || time;
      if (t.kind === "tool_call") {
        let result: TraceItem | undefined;
        for (let j = k + 1; j < items.length; j++) {
          const r = items[j];
          if (r.kind === "tool_result" && (r.tool == null || r.tool === t.tool)) {
            result = r;
            consumed.add(j);
            break;
          }
        }
        nodes.push(toolNode(idx, k, t, result, stepTime));
        return;
      }
      if (t.kind === "tool_result") {
        // Orphan result (legacy/partial trace) — still render via ToolIO.
        nodes.push(toolNode(idx, k, { kind: "tool_call", tool: t.tool }, t, stepTime));
        return;
      }
      if (t.kind === "reasoning") {
        nodes.push(labelNode(idx, k, COLOR.researcher, "Researcher", stepTime, "timeline-reasoning"));
        return;
      }
      if (t.kind === "plan") {
        nodes.push(labelNode(idx, k, COLOR.planner, "Planner", stepTime, "timeline-plan"));
        return;
      }
      if (t.kind === "critique") {
        const label = t.role ? `Critic (${t.role})` : "Critic";
        nodes.push(labelNode(idx, k, COLOR.critic, label, stepTime, "timeline-critique"));
        return;
      }
      if (t.kind === "verification") {
        const pass = t.verdict === "pass";
        const label = `Verify${t.verdict ? ` (${t.verdict})` : ""}`;
        nodes.push(
          labelNode(idx, k, pass ? COLOR.ok : COLOR.err, label, stepTime, "timeline-verification"),
        );
        return;
      }
      // Generic fallback so an unknown future kind renders rather than vanishing.
      nodes.push(labelNode(idx, k, COLOR.researcher, t.kind, stepTime, "timeline-other"));
    });
    return nodes;
  }

  // Walk messages -> turns (each assistant message + its nearest preceding user message).
  const turns: Turn[] = [];
  messages.forEach((m, i) => {
    if (m.role !== "assistant") return;
    let question = "";
    for (let j = i - 1; j >= 0; j--) {
      if (messages[j].role === "user") {
        question = messages[j].content;
        break;
      }
    }
    const items = trace[i]?.length ? trace[i] : (m.meta?.trace ?? []);
    const context = m.meta?.context ?? (i === lastAssistantIndex ? liveContext : null);
    // Per-turn usage from meta; for the newest (live) turn that hasn't persisted yet, fall back to
    // the live usage event so the header can still show tokens/time once the stream reports them.
    const usage = m.meta?.usage ?? (i === lastAssistantIndex ? liveUsage : null);
    const isLive = i === lastAssistantIndex && busy && !m.meta?.usage;
    const nodes = buildNodes(i, items, context ?? null, clockUTC(m.created_at));
    const toolCalls = items.filter((t) => t.kind === "tool_call").length;
    const status = isLive
      ? COLOR.live
      : items.some((t) => t.kind === "verification" && t.verdict !== "pass") ||
          items.some((t) => t.kind === "tool_result" && t.ok === false)
        ? COLOR.err
        : COLOR.ok;
    turns.push({
      index: i,
      question: question || "(no question)",
      nodes,
      toolCalls,
      tokens: usage?.total_tokens ?? null,
      elapsedMs: usage?.elapsed_ms ?? null,
      createdAt: m.created_at,
      isLive,
      status,
    });
  });

  // Newest turn group on top.
  const reversed = [...turns].reverse();
  const newestIndex = turns.length ? turns[turns.length - 1].index : -1;

  return (
    <div data-testid="activity-timeline">
      {/* Filter chips: narrow the spine to Tools / Reasoning / Context (or All). */}
      <div
        role="group"
        aria-label="Filter activity"
        style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap", marginBottom: "0.5rem" }}
      >
        {FILTERS.map((f) => {
          const active = filter === f.id;
          return (
            <button
              key={f.id}
              data-testid="timeline-filter"
              aria-pressed={active}
              onClick={() => setFilter(f.id)}
              style={{
                fontSize: "0.72rem",
                padding: "0.1rem 0.55rem",
                borderRadius: "1rem",
                cursor: "pointer",
                border: `1px solid ${active ? COLOR.context : "rgba(127,127,127,0.4)"}`,
                background: active ? "rgba(74,144,217,0.12)" : "transparent",
                color: active ? COLOR.context : READABLE,
                fontWeight: active ? 600 : 400,
              }}
            >
              {f.label}
            </button>
          );
        })}
      </div>

      {reversed.length === 0 ? (
        <p data-testid="timeline-empty" style={{ color: "#888", fontSize: "0.8rem", margin: 0 }}>
          Activity from each question will appear here, newest first.
        </p>
      ) : (
        <div style={{ maxHeight: "60vh", overflowY: "auto", display: "flex", flexDirection: "column", gap: "0.4rem" }}>
          {reversed.map((turn) => {
            const nodes = visibleNodes(turn.nodes, filter);
            // A turn with nothing under the active filter is hidden entirely.
            if (filter !== "all" && nodes.length === 0) return null;
            const isNewest = turn.index === newestIndex;
            // Newest turn (and any live turn) expanded by default; older collapsed. User overrides win.
            const defaultOpen = isNewest || turn.isLive;
            const open = overrides[turn.index] ?? defaultOpen;
            const meta = [
              turn.toolCalls ? `${turn.toolCalls} tool call${turn.toolCalls > 1 ? "s" : ""}` : null,
              turn.tokens != null ? `~${compactTok(turn.tokens)} tok` : null,
              turn.elapsedMs != null ? fmtMs(turn.elapsedMs) : null,
              relTime(turn.createdAt, now),
            ]
              .filter(Boolean)
              .join(" · ");
            return (
              <div
                key={turn.index}
                data-testid="timeline-turn"
                style={{
                  border: "1px solid rgba(127,127,127,0.18)",
                  borderRadius: 6,
                  background: turn.isLive ? "rgba(176,111,0,0.05)" : "transparent",
                }}
              >
                <button
                  data-testid="timeline-turn-header"
                  aria-expanded={open}
                  onClick={() => setOverrides((o) => ({ ...o, [turn.index]: !open }))}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    width: "100%",
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    padding: "0.4rem 0.5rem",
                    textAlign: "left",
                    font: "inherit",
                  }}
                >
                  <span aria-hidden style={{ color: READABLE, fontSize: "0.72rem", flex: "0 0 auto" }}>
                    {open ? "▾" : "▸"}
                  </span>
                  {/* Status dot (or pulsing live indicator). */}
                  {turn.isLive ? (
                    <span
                      data-testid="timeline-live"
                      title="Generating…"
                      style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem", flex: "0 0 auto" }}
                    >
                      <span
                        aria-hidden
                        style={{
                          width: 8,
                          height: 8,
                          borderRadius: "50%",
                          background: COLOR.live,
                          animation: "tlpulse 1.2s ease-in-out infinite",
                        }}
                      />
                      <span style={{ color: COLOR.live, fontSize: "0.7rem", fontWeight: 600 }}>live</span>
                    </span>
                  ) : (
                    <span
                      aria-hidden
                      style={{ width: 8, height: 8, borderRadius: "50%", background: turn.status, flex: "0 0 auto" }}
                    />
                  )}
                  <span
                    style={{
                      flex: "1 1 auto",
                      minWidth: 0,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      color: "#1f2937",
                    }}
                  >
                    {turn.question}
                  </span>
                </button>
                <div
                  style={{ padding: "0 0.5rem 0.1rem 1.55rem", fontSize: "0.72rem", color: READABLE }}
                  title={turn.createdAt ?? "in progress"}
                >
                  {meta}
                </div>

                {open && (
                  <div
                    data-testid="timeline-turn-body"
                    style={{
                      margin: "0.3rem 0.5rem 0.5rem 0.9rem",
                      paddingLeft: "0.7rem",
                      borderLeft: "2px solid rgba(127,127,127,0.25)",
                      display: "flex",
                      flexDirection: "column",
                      gap: "0.4rem",
                      fontSize: "0.85rem",
                      color: "#555",
                    }}
                  >
                    {nodes.length === 0 ? (
                      <span style={{ color: "#888", fontSize: "0.78rem" }}>No activity for this turn.</span>
                    ) : (
                      nodes.map((node) => (
                        <div key={node.key} data-testid="timeline-node" style={{ position: "relative" }}>
                          {/* The spine node: a small colored dot pinned to the left border. */}
                          <span
                            aria-hidden
                            style={{
                              position: "absolute",
                              left: "-0.95rem",
                              top: "0.35rem",
                              width: 7,
                              height: 7,
                              borderRadius: "50%",
                              background: node.dot,
                              boxShadow: "0 0 0 2px #fff",
                            }}
                          />
                          {node.render()}
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Subtle opacity pulse for the live dot (no heavy motion). */}
      <style>{"@keyframes tlpulse{0%,100%{opacity:1}50%{opacity:0.35}}"}</style>
    </div>
  );
}
