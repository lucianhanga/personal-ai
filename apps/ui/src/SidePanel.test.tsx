import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import type { ChatMessage, ContextBreakdown } from "./api";
import { SidePanel } from "./SidePanel";

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
      messages={props.messages ?? MESSAGES}
      trace={props.trace ?? {}}
      usage={props.usage ?? null}
      totals={props.totals ?? { tokens: 0, ms: 0, turns: 0 }}
      contexts={props.contexts ?? {}}
      busy={props.busy ?? false}
      collapsed={props.collapsed ?? false}
      setCollapsed={vi.fn()}
    />,
  );
}

test("renders the Activity panel header (title + collapse), no log buttons", () => {
  renderPanel();
  // The panel is titled "Activity"; the old tool-log / app-log buttons are gone.
  expect(screen.getByText("Activity")).toBeInTheDocument();
  expect(screen.getByTestId("side-toggle")).toBeInTheDocument();
  expect(screen.queryByTestId("toollog-show")).toBeNull();
  expect(screen.queryByTestId("applogs-show")).toBeNull();
});

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
  // A live context (via the per-turn map) + usage: the meter shows the window line, but the
  // composition breakdown is only in the timeline's turn (context-breakdown comes from the timeline).
  renderPanel({
    contexts: { 1: CONTEXT },
    usage: { prompt_tokens: 4, completion_tokens: 2, total_tokens: 6, context_limit: 100, elapsed_ms: 500 },
  });
  expect(screen.getByTestId("context-meter")).toBeInTheDocument();
  // Exactly one composition breakdown on the page — the timeline's, not a duplicated meter one.
  expect(screen.getAllByTestId("context-breakdown")).toHaveLength(1);
});

test("with no usage there is no ContextMeter, but the timeline still renders", () => {
  renderPanel({ usage: null, contexts: {} });
  expect(screen.queryByTestId("context-meter")).toBeNull();
  expect(screen.getByTestId("activity-timeline")).toBeInTheDocument();
});
