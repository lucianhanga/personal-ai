import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { ActivityTimeline } from "./ActivityTimeline";
import type { ChatMessage, ContextBreakdown, TraceItem } from "./api";

const CONTEXT: ContextBreakdown = {
  items: [{ label: "grounding", count: 1, chars: 400 }],
  total_chars: 400,
};

// Two persisted turns: an older one (tool call), and a newer one (reasoning + context + usage).
function twoTurnMessages(): ChatMessage[] {
  return [
    { role: "user", content: "first question" },
    {
      role: "assistant",
      content: "first answer",
      created_at: "2020-01-01T00:00:00Z",
      meta: {
        trace: [
          { kind: "tool_call", tool: "web_search", args: { query: "x" } },
          { kind: "tool_result", tool: "web_search", ok: true, output: { results: [] } },
        ],
        usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15, elapsed_ms: 800 },
      },
    },
    { role: "user", content: "second question" },
    {
      role: "assistant",
      content: "second answer",
      created_at: "2020-01-01T00:05:00Z",
      meta: {
        trace: [{ kind: "reasoning", text: "let me think" }] as TraceItem[],
        context: CONTEXT,
        usage: { prompt_tokens: 20, completion_tokens: 8, total_tokens: 28, elapsed_ms: 1200 },
      },
    },
  ];
}

function renderTimeline(overrides: Partial<React.ComponentProps<typeof ActivityTimeline>> = {}) {
  return render(
    <ActivityTimeline
      messages={overrides.messages ?? twoTurnMessages()}
      trace={overrides.trace ?? {}}
      liveContext={overrides.liveContext ?? null}
      liveUsage={overrides.liveUsage ?? null}
      busy={overrides.busy ?? false}
    />,
  );
}

test("empty state with no messages", () => {
  renderTimeline({ messages: [] });
  expect(screen.getByTestId("timeline-empty")).toBeInTheDocument();
  expect(screen.queryByTestId("timeline-turn")).toBeNull();
});

test("newest turn renders first and expanded; older collapsed", () => {
  renderTimeline();
  const headers = screen.getAllByTestId("timeline-turn-header");
  // Newest turn group is on top (reverse-chronological).
  expect(headers[0]).toHaveTextContent("second question");
  expect(headers[1]).toHaveTextContent("first question");
  // Newest expanded, older collapsed.
  expect(headers[0]).toHaveAttribute("aria-expanded", "true");
  expect(headers[1]).toHaveAttribute("aria-expanded", "false");
});

test("a tool_call/result pair renders one ToolIO node", () => {
  renderTimeline();
  // Expand the older turn (collapsed by default) to reveal its tool node.
  const headers = screen.getAllByTestId("timeline-turn-header");
  fireEvent.click(headers[1]);
  // One ToolIO for the call+result pair, not two rows.
  expect(screen.getAllByTestId("toolio")).toHaveLength(1);
  expect(screen.getByTestId("toolio-summary")).toHaveTextContent("web_search");
});

test("context node renders for a turn with a context snapshot", () => {
  renderTimeline();
  // The newest turn (expanded) carries the context snapshot.
  expect(screen.getByTestId("timeline-context")).toHaveTextContent("Context assembled");
});

test("clicking a header toggles expand/collapse", () => {
  renderTimeline();
  const newest = screen.getAllByTestId("timeline-turn-header")[0];
  expect(newest).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(newest);
  expect(newest).toHaveAttribute("aria-expanded", "false");
});

test("filter chips hide non-matching nodes within turns", () => {
  renderTimeline();
  // Default All: the newest turn shows both its context and reasoning nodes.
  expect(screen.getByTestId("timeline-context")).toBeInTheDocument();
  // The reasoning node is the agent NAME marker only — the prose ("let me think") is not shown.
  const reasoning = screen.getByTestId("timeline-reasoning");
  expect(reasoning).toHaveTextContent("Researcher");
  expect(reasoning).not.toHaveTextContent("let me think");

  // Filter -> Tools: context + reasoning hidden, and turns with no tool node disappear.
  const toolsChip = screen.getAllByTestId("timeline-filter").find((b) => b.textContent === "Tools")!;
  fireEvent.click(toolsChip);
  expect(toolsChip).toHaveAttribute("aria-pressed", "true");
  expect(screen.queryByTestId("timeline-context")).toBeNull();
  expect(screen.queryByTestId("timeline-reasoning")).toBeNull();
  // Only the tool turn survives the Tools filter; the reasoning-only turn is hidden entirely.
  const toolTurns = screen.getAllByTestId("timeline-turn-header");
  expect(toolTurns).toHaveLength(1);
  expect(toolTurns[0]).toHaveTextContent("first question");
  // Expand it to reveal its (sole) ToolIO node.
  fireEvent.click(toolTurns[0]);
  expect(screen.getByTestId("toolio")).toBeInTheDocument();

  // Filter -> Context: only the context node remains.
  const contextChip = screen.getAllByTestId("timeline-filter").find((b) => b.textContent === "Context")!;
  fireEvent.click(contextChip);
  expect(screen.getByTestId("timeline-context")).toBeInTheDocument();
  expect(screen.queryByTestId("toolio")).toBeNull();
});

test("busy shows the pulsing live indicator on the newest turn, kept expanded", () => {
  const messages: ChatMessage[] = [
    { role: "user", content: "in flight" },
    // The live assistant turn has no usage yet (still streaming).
    { role: "assistant", content: "" },
  ];
  render(
    <ActivityTimeline
      messages={messages}
      trace={{ 1: [{ kind: "reasoning", text: "thinking" }] }}
      liveContext={CONTEXT}
      liveUsage={null}
      busy
    />,
  );
  expect(screen.getByTestId("timeline-live")).toBeInTheDocument();
  expect(screen.getByTestId("timeline-turn-header")).toHaveAttribute("aria-expanded", "true");
  // The live turn pulls its context from liveContext.
  expect(screen.getByTestId("timeline-context")).toBeInTheDocument();
});

test("falls back to live trace from the trace map when meta.trace is absent", () => {
  const messages: ChatMessage[] = [
    { role: "user", content: "q" },
    { role: "assistant", content: "a", created_at: "2020-01-01T00:00:00Z" },
  ];
  render(
    <ActivityTimeline
      messages={messages}
      trace={{ 1: [{ kind: "plan", text: "do the thing" }] }}
      liveContext={null}
      liveUsage={null}
      busy={false}
    />,
  );
  // The timeline shows the agent NAME + a UTC timestamp, NOT the reasoning prose (which stays in
  // the transcript's per-message Details).
  const plan = screen.getByTestId("timeline-plan");
  expect(plan).toHaveTextContent("Planner");
  expect(plan).toHaveTextContent("00:00:00Z");
  expect(plan).not.toHaveTextContent("do the thing");
});

test("egress-blocked tool keeps the Allow affordance via ToolIO", () => {
  const onAllowHost = vi.fn();
  const messages: ChatMessage[] = [
    { role: "user", content: "fetch it" },
    {
      role: "assistant",
      content: "",
      meta: {
        trace: [
          { kind: "tool_call", tool: "fetch", args: { url: "http://x" } },
          {
            kind: "tool_result",
            tool: "fetch",
            ok: false,
            error: "egress blocked: host 'example.com' is not in the egress allowlist",
          },
        ],
      },
    },
  ];
  render(
    <ActivityTimeline
      messages={messages}
      trace={{}}
      liveContext={null}
      liveUsage={null}
      busy={false}
      onAllowHost={onAllowHost}
    />,
  );
  // The pending egress block auto-expands the ToolIO; Allow is reachable without extra clicks.
  fireEvent.click(screen.getByTestId("egress-allow-btn"));
  expect(onAllowHost).toHaveBeenCalledWith("example.com");
});
