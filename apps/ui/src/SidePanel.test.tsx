import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import type { ChatMessage, ContextBreakdown } from "./api";
import { SidePanel } from "./SidePanel";

// ToolLog / AppLogs fetch on mount; stub the network so the panel renders in isolation.
vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, fetchToolLog: vi.fn().mockResolvedValue([]), fetchLogs: vi.fn().mockResolvedValue([]) };
});

const CONTEXT: ContextBreakdown = {
  items: [{ label: "grounding", count: 1, chars: 400 }],
  total_chars: 400,
};

const MESSAGES: ChatMessage[] = [
  { role: "user", content: "hello" },
  {
    role: "assistant",
    content: "hi",
    created_at: "2020-01-01T00:00:00Z",
    meta: { context: CONTEXT, usage: { prompt_tokens: 4, completion_tokens: 2, total_tokens: 6, elapsed_ms: 500 } },
  },
];

function renderPanel(props: Partial<React.ComponentProps<typeof SidePanel>> = {}) {
  return render(
    <SidePanel
      token="demo"
      conversationId={null}
      messages={props.messages ?? MESSAGES}
      trace={props.trace ?? {}}
      usage={props.usage ?? null}
      totals={props.totals ?? { tokens: 0, ms: 0, turns: 0 }}
      context={props.context ?? null}
      busy={props.busy ?? false}
      collapsed={props.collapsed ?? false}
      setCollapsed={vi.fn()}
      showLog={props.showLog ?? false}
      setShowLog={vi.fn()}
      showAppLogs={props.showAppLogs ?? false}
      setShowAppLogs={vi.fn()}
    />,
  );
}

test("renders the activity timeline as the centerpiece", () => {
  renderPanel();
  expect(screen.getByTestId("activity-timeline")).toBeInTheDocument();
  expect(screen.getByTestId("timeline-turn")).toBeInTheDocument();
});

test("collapsed shows just the expand toggle, no timeline", () => {
  renderPanel({ collapsed: true });
  expect(screen.getByTestId("side-toggle")).toBeInTheDocument();
  expect(screen.queryByTestId("activity-timeline")).toBeNull();
});

test("live context is not duplicated: ContextMeter omits the composition (lives in the timeline)", () => {
  // A live context + usage: the meter shows the window line, but the composition breakdown is only
  // in the timeline's newest turn (context-breakdown comes from the timeline, not the meter).
  renderPanel({
    context: CONTEXT,
    usage: { prompt_tokens: 4, completion_tokens: 2, total_tokens: 6, context_limit: 100, elapsed_ms: 500 },
  });
  expect(screen.getByTestId("context-meter")).toBeInTheDocument();
  // Exactly one composition breakdown on the page — the timeline's, not a duplicated meter one.
  expect(screen.getAllByTestId("context-breakdown")).toHaveLength(1);
});

test("with no usage there is no ContextMeter, but the timeline still renders", () => {
  renderPanel({ usage: null, context: null });
  expect(screen.queryByTestId("context-meter")).toBeNull();
  expect(screen.getByTestId("activity-timeline")).toBeInTheDocument();
});
