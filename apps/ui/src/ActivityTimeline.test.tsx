import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { ActivityTimeline, type LiveActivity } from "./ActivityTimeline";
import type { ChatMessage, ContextBreakdown, ResourceActivity, TraceItem } from "./api";

const CONTEXT: ContextBreakdown = {
  items: [{ label: "grounding", count: 1, chars: 400 }],
  total_chars: 400,
};

// Two completed turns: an older one (tool call) whose context comes via the live `contexts` map,
// and a newer one (reasoning) whose context is persisted on `m.meta.context`. Both must show a
// "Context assembled" node — the older turn's context must NOT go missing.
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
      // The older turn (index 1) gets its context from the live map; the newer (index 3) from meta.
      contexts={overrides.contexts ?? { 1: CONTEXT }}
      liveUsage={overrides.liveUsage ?? null}
      busy={overrides.busy ?? false}
      liveActivities={overrides.liveActivities ?? []}
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

test("renders a draft answer marker node, kept under the Reasoning filter (#393)", () => {
  const messages: ChatMessage[] = [
    { role: "user", content: "q" },
    {
      role: "assistant",
      content: "final",
      created_at: "2020-01-01T00:00:00Z",
      meta: { trace: [{ kind: "draft", text: "proposed", attempt: 1 }] as TraceItem[] },
    },
  ];
  renderTimeline({ messages, contexts: {} });
  // Newest turn is expanded by default, so the draft marker shows.
  expect(screen.getByTestId("timeline-draft")).toBeInTheDocument();
  // It's reasoning-kind: the Reasoning filter keeps it.
  const reasoning = screen.getAllByTestId("timeline-filter").find((b) => b.textContent === "Reasoning")!;
  fireEvent.click(reasoning);
  expect(screen.getByTestId("timeline-draft")).toBeInTheDocument();
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

test("every turn shows its own Context assembled node (older via the contexts map, newer via meta)", () => {
  renderTimeline();
  // The newest turn (expanded by default) carries its context from m.meta.context.
  expect(screen.getByTestId("timeline-context")).toHaveTextContent("Context assembled");
  // Expand the older turn (collapsed by default): its context comes from the live `contexts` map and
  // must NOT be missing — the core fix for #388 (context shown for EVERY turn, not just the latest).
  const headers = screen.getAllByTestId("timeline-turn-header");
  fireEvent.click(headers[1]);
  expect(screen.getAllByTestId("timeline-context")).toHaveLength(2);
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

  // Filter -> Context: only context nodes remain (no ToolIO). Both turns now carry a context node —
  // the older (still expanded from above) via the contexts map, the newest via meta — so we see two.
  const contextChip = screen.getAllByTestId("timeline-filter").find((b) => b.textContent === "Context")!;
  fireEvent.click(contextChip);
  expect(screen.getAllByTestId("timeline-context")).toHaveLength(2);
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
      contexts={{ 1: CONTEXT }}
      liveUsage={null}
      busy
    />,
  );
  expect(screen.getByTestId("timeline-live")).toBeInTheDocument();
  expect(screen.getByTestId("timeline-turn-header")).toHaveAttribute("aria-expanded", "true");
  // The live turn pulls its context from the per-turn contexts map.
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
      contexts={{}}
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
      contexts={{}}
      liveUsage={null}
      busy={false}
      onAllowHost={onAllowHost}
    />,
  );
  // The pending egress block auto-expands the ToolIO; Allow is reachable without extra clicks.
  fireEvent.click(screen.getByTestId("egress-allow-btn"));
  expect(onAllowHost).toHaveBeenCalledWith("example.com");
});

test("shows each step's own per-step ts, falling back to the turn clock when absent (#384)", () => {
  const messages: ChatMessage[] = [
    { role: "user", content: "q" },
    {
      role: "assistant",
      content: "a",
      created_at: "2020-01-01T00:00:00Z",
      meta: {
        trace: [
          { kind: "plan", text: "p", ts: "2020-01-01T03:04:05Z" },
          { kind: "reasoning", text: "r" }, // no ts -> falls back to the turn clock
        ] as TraceItem[],
      },
    },
  ];
  renderTimeline({ messages }); // single (newest) turn is expanded by default
  // The plan step shows its OWN time, not the turn's 00:00:00.
  expect(screen.getByTestId("timeline-plan")).toHaveTextContent("03:04:05Z");
  // The ts-less reasoning step falls back to the turn's created_at clock.
  expect(screen.getByTestId("timeline-reasoning")).toHaveTextContent("00:00:00Z");
});

// --- resource-processing activities (#424) -------------------------------------------------------

const ACT_IMAGE: ResourceActivity = {
  kind: "resource",
  action: "image_described",
  text: "Described image — cat.jpg",
  ref: "cat.jpg",
  ts: 1_577_836_801, // 2020-01-01T00:00:01Z
  model: "qwen2.5-vl:7b",
  ms: 2300,
};
const ACT_DOC: ResourceActivity = {
  kind: "resource",
  action: "document_extracted",
  text: "Extracted document — spec.pdf",
  ref: "spec.pdf",
  ts: 1_577_836_803, // 2020-01-01T00:00:03Z
  model: null,
  ms: 12,
};

// A turn whose user message carries persisted resource activities (#424).
function turnWithActivities(activities: ResourceActivity[]): ChatMessage[] {
  return [
    { role: "user", content: "what breed?", activities },
    {
      role: "assistant",
      content: "a maine coon",
      created_at: "2020-01-01T00:00:10Z",
      meta: {
        trace: [{ kind: "reasoning", text: "thinking" }] as TraceItem[],
        context: CONTEXT,
        usage: { prompt_tokens: 20, completion_tokens: 8, total_tokens: 28, elapsed_ms: 1200 },
      },
    },
  ];
}

test("(history) persisted resource activity renders as a done resource node with model + ms", () => {
  renderTimeline({ messages: turnWithActivities([ACT_IMAGE]), contexts: {} });
  const node = screen.getByTestId("timeline-resource");
  expect(node).toHaveAttribute("data-status", "done");
  expect(node).toHaveTextContent("Described image — cat.jpg");
  // Tier-1 status pill carries the WORD (not color-only).
  expect(screen.getByTestId("resourceio-status")).toHaveTextContent("done");
  // Expand Tier-2 -> model + duration.
  fireEvent.click(screen.getByTestId("resourceio-summary"));
  const detail = screen.getByTestId("resourceio-detail");
  expect(detail).toHaveTextContent("qwen2.5-vl:7b");
  expect(detail).toHaveTextContent("2.3 s"); // fmtMs(2300)
});

test("(history) resource nodes render before the context node, ordered by ts (#424)", () => {
  // Two resources out of ts order in the array; the timeline sorts them ascending and puts both
  // before the "Context assembled" node.
  renderTimeline({ messages: turnWithActivities([ACT_DOC, ACT_IMAGE]), contexts: {} });
  const nodes = screen.getAllByTestId("timeline-node");
  // node[0] = image (ts ...01), node[1] = doc (ts ...03), node[2] = context, node[3] = reasoning.
  expect(nodes[0]).toHaveTextContent("Described image — cat.jpg");
  expect(nodes[1]).toHaveTextContent("Extracted document — spec.pdf");
  expect(nodes[2]).toHaveTextContent("Context assembled");
});

test("(history) the turn meta line gains an 'N resources' segment", () => {
  renderTimeline({ messages: turnWithActivities([ACT_IMAGE, ACT_DOC]), contexts: {} });
  expect(screen.getByTestId("timeline-turn-header").parentElement).toHaveTextContent("2 resources");
});

test("(filter) the Resources chip shows only resource nodes and hides turns with none", () => {
  // Two turns: an older plain one (no activities) and the newest one (with activities, open by
  // default so its resource nodes render).
  const messages: ChatMessage[] = [
    { role: "user", content: "plain question" },
    {
      role: "assistant",
      content: "plain answer",
      created_at: "2020-01-01T00:00:00Z",
      meta: { trace: [{ kind: "reasoning", text: "x" }] as TraceItem[] },
    },
    ...turnWithActivities([ACT_IMAGE]),
  ];
  renderTimeline({ messages, contexts: {} });
  const resourcesChip = screen.getAllByTestId("timeline-filter").find((b) => b.textContent === "Resources")!;
  fireEvent.click(resourcesChip);
  // Only the resource node remains; the resource-less turn is hidden entirely.
  expect(screen.getAllByTestId("timeline-resource")).toHaveLength(1);
  expect(screen.queryByTestId("timeline-reasoning")).toBeNull();
});

test("(legacy) a turn without activities renders exactly as today — nothing new", () => {
  renderTimeline(); // the default two-turn fixture has no activities
  expect(screen.queryByTestId("timeline-resource")).toBeNull();
  expect(screen.queryByTestId("timeline-preturn")).toBeNull();
  // No "N resources" segment leaks into the meta line.
  expect(screen.getAllByTestId("timeline-turn-header")[0].parentElement).not.toHaveTextContent(
    "resource",
  );
});

test("(live) the pre-turn cluster shows in-progress + done activities, role=status", () => {
  const live: LiveActivity[] = [
    { ...ACT_IMAGE, state: "in-progress", model: null, ms: null },
    { ...ACT_DOC, state: "done" },
  ];
  renderTimeline({ messages: [], liveActivities: live });
  const cluster = screen.getByTestId("timeline-preturn");
  expect(cluster).toHaveAttribute("role", "status");
  expect(cluster).toHaveTextContent("Preparing your message");
  // The in-progress image keeps the cluster "live".
  expect(cluster).toHaveTextContent("live");
  const nodes = screen.getAllByTestId("timeline-resource");
  expect(nodes[0]).toHaveAttribute("data-status", "in-progress"); // image (ts ...01) first
  expect(nodes[1]).toHaveAttribute("data-status", "done"); // doc (ts ...03)
});

test("(live) the cluster settles to a non-live dot once all activities are done", () => {
  const live: LiveActivity[] = [{ ...ACT_IMAGE, state: "done" }];
  renderTimeline({ messages: [], liveActivities: live });
  const cluster = screen.getByTestId("timeline-preturn");
  expect(cluster).not.toHaveTextContent("live");
  expect(screen.getByTestId("resourceio-status")).toHaveTextContent("done");
});

test("(error) a failed describe persists as a red error node with its message", () => {
  const errored: ResourceActivity = {
    ...ACT_IMAGE,
    status: "error",
    error: "vision model unavailable",
  };
  renderTimeline({ messages: turnWithActivities([errored]), contexts: {} });
  const node = screen.getByTestId("timeline-resource");
  expect(node).toHaveAttribute("data-status", "error");
  expect(screen.getByTestId("resourceio-status")).toHaveTextContent("error");
  fireEvent.click(screen.getByTestId("resourceio-summary"));
  expect(screen.getByTestId("resourceio-error")).toHaveTextContent("vision model unavailable");
});

test("(removed-before-submit) an empty liveActivities array renders no cluster", () => {
  renderTimeline({ messages: [], liveActivities: [] });
  expect(screen.queryByTestId("timeline-preturn")).toBeNull();
  // With no turns and no cluster, the empty-state copy shows.
  expect(screen.getByTestId("timeline-empty")).toBeInTheDocument();
});

// --- RAG-pipeline prelude steps (#437): indexing / retrieval / ner --------------------------------

const RAG_INDEXING: TraceItem = {
  kind: "indexing",
  text: "Indexed report.pdf",
  ts: "2020-01-01T00:00:03Z",
  ref: "report.pdf",
  chunks: 48,
  ms: 1400,
};
const RAG_RETRIEVAL: TraceItem = {
  kind: "retrieval",
  text: "Retrieved 3 passages",
  ts: "2020-01-01T00:00:05Z",
  ms: 320,
  query: "Q3 runway guidance from the board deck",
  top_k: 8,
  hits: 3,
  scope: "union",
  citations: [
    { source: "notes.md", score: 0.61 },
    { source: "Q3-board.pdf", score: 0.82 },
    { source: "Q3-board.pdf", score: 0.74 },
  ],
};

// A turn whose assistant meta["trace"] leads with the RAG prelude (the backend prepends it), then
// an agent step — mirroring the persisted, ordered array the renderer honors.
function ragTurn(trace: TraceItem[]): ChatMessage[] {
  return [
    { role: "user", content: "what did the deck say about runway?" },
    {
      role: "assistant",
      content: "it said 18 months",
      created_at: "2020-01-01T00:00:10Z",
      meta: {
        trace: [...trace, { kind: "reasoning", text: "thinking" }] as TraceItem[],
        context: CONTEXT,
        usage: { prompt_tokens: 20, completion_tokens: 8, total_tokens: 28, elapsed_ms: 1200 },
      },
    },
  ];
}

test("(#437) indexing + retrieval render before the context node, in array order", () => {
  renderTimeline({ messages: ragTurn([RAG_INDEXING, RAG_RETRIEVAL]), contexts: {} });
  const nodes = screen.getAllByTestId("timeline-node");
  // node[0] = indexing, node[1] = retrieval, node[2] = context, node[3] = reasoning (agent).
  expect(nodes[0]).toHaveTextContent("Indexed report.pdf - 48 chunks");
  expect(nodes[1]).toHaveTextContent("Retrieved 3 passages (union)");
  expect(nodes[2]).toHaveTextContent("Context assembled");
  // The RAG chips precede the agent reasoning step.
  expect(screen.getByTestId("timeline-indexing")).toBeInTheDocument();
  expect(screen.getByTestId("timeline-retrieval")).toBeInTheDocument();
});

test("(#437) indexing Tier-2 shows chunks + duration; success has no error", () => {
  renderTimeline({ messages: ragTurn([RAG_INDEXING]), contexts: {} });
  const chip = screen.getByTestId("timeline-indexing");
  expect(chip).toHaveAttribute("data-status", "done");
  fireEvent.click(within(chip).getByTestId("pipelineio-summary"));
  const detail = within(chip).getByTestId("pipelineio-detail");
  expect(detail).toHaveTextContent("Chunks: 48");
  expect(detail).toHaveTextContent("Duration: 1.4 s"); // fmtMs(1400)
  expect(within(chip).queryByTestId("pipelineio-error")).toBeNull();
});

test("(#437) retrieval citation list is ordered by descending score; numeric score is accessible", () => {
  renderTimeline({ messages: ragTurn([RAG_RETRIEVAL]), contexts: {} });
  const chip = screen.getByTestId("timeline-retrieval");
  // hits>0 -> the chip defaults open, so the citation <ol> is present.
  const list = within(chip).getByTestId("retrieval-citations");
  const scores = within(list).getAllByTestId("retrieval-score").map((n) => n.textContent);
  expect(scores).toEqual(["0.82", "0.74", "0.61"]); // sorted desc, two decimals
  // Query + meta header present in Tier 2.
  expect(chip).toHaveTextContent("Top-k: 8");
  expect(chip).toHaveTextContent("Hits: 3");
});

test("(#437) a 0-hit retrieval renders as a 'No passages retrieved' signal, pill done", () => {
  const zero: TraceItem = {
    kind: "retrieval",
    text: "Retrieved 0 passages",
    ts: "2020-01-01T00:00:05Z",
    ms: 12,
    query: "obscure thing",
    top_k: 8,
    hits: 0,
    scope: "global",
    citations: [],
  };
  renderTimeline({ messages: ragTurn([zero]), contexts: {} });
  const chip = screen.getByTestId("timeline-retrieval");
  expect(chip).toHaveTextContent("No passages retrieved (global)");
  expect(within(chip).getByTestId("pipelineio-status")).toHaveTextContent("done"); // signal, not error
  fireEvent.click(within(chip).getByTestId("pipelineio-summary"));
  expect(chip).toHaveTextContent("No passages matched.");
  expect(within(chip).queryByTestId("retrieval-citations")).toBeNull();
});

test("(#437) the RAG filter shows only the three kinds and hides turns with none", () => {
  // An older RAG-less turn + the newest RAG turn (open by default).
  const messages: ChatMessage[] = [
    { role: "user", content: "plain question" },
    {
      role: "assistant",
      content: "plain answer",
      created_at: "2020-01-01T00:00:00Z",
      meta: { trace: [{ kind: "reasoning", text: "x" }] as TraceItem[] },
    },
    ...ragTurn([RAG_INDEXING, RAG_RETRIEVAL]),
  ];
  renderTimeline({ messages, contexts: {} });
  const ragChip = screen.getAllByTestId("timeline-filter").find((b) => b.textContent === "RAG")!;
  fireEvent.click(ragChip);
  // Only the indexing + retrieval chips remain; the reasoning + context nodes are hidden.
  expect(screen.getByTestId("timeline-indexing")).toBeInTheDocument();
  expect(screen.getByTestId("timeline-retrieval")).toBeInTheDocument();
  expect(screen.queryByTestId("timeline-reasoning")).toBeNull();
  expect(screen.queryByTestId("timeline-context")).toBeNull();
});

test("(#437) ner is dormant: no ner item -> no chip; a ner item -> entities chip + breakdown", () => {
  // No ner item on a normal RAG turn -> no chip (dormant).
  const { unmount } = renderTimeline({ messages: ragTurn([RAG_RETRIEVAL]), contexts: {} });
  expect(screen.queryByTestId("timeline-ner")).toBeNull();
  unmount();
  // Phase-6 fixture: a ner item -> the entities chip renders with the type breakdown.
  const ner: TraceItem = {
    kind: "ner",
    text: "Extracted 6 entities",
    ts: "2020-01-01T00:00:06Z",
    count: 6,
    types: [
      { type: "PERSON", count: 3 },
      { type: "ORG", count: 2 },
      { type: "DATE", count: 1 },
    ],
  };
  renderTimeline({ messages: ragTurn([ner]), contexts: {} });
  const chip = screen.getByTestId("timeline-ner");
  expect(chip).toHaveTextContent("Extracted 6 entities");
  fireEvent.click(within(chip).getByTestId("pipelineio-summary"));
  expect(chip).toHaveTextContent("PERSON: 3 - ORG: 2 - DATE: 1");
});

test("(#437 legacy) a turn with none of the new kinds renders exactly as today", () => {
  renderTimeline(); // default two-turn fixture has no RAG items
  expect(screen.queryByTestId("timeline-indexing")).toBeNull();
  expect(screen.queryByTestId("timeline-retrieval")).toBeNull();
  expect(screen.queryByTestId("timeline-ner")).toBeNull();
});
