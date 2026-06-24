import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { MessageDetails } from "./MessageDetails";

const STEPS = [
  { phase: "call" as const, tool: "web_search", args: { query: "x" } },
  { phase: "result" as const, tool: "web_search", ok: true, output: { results: [] } },
];

test("renders nothing without steps or reasoning", () => {
  const { container } = render(<MessageDetails />);
  expect(container).toBeEmptyDOMElement();
});

test("collapsed by default; expands to show tool calls and reasoning", () => {
  render(<MessageDetails steps={STEPS} thinking="because reasons" />);
  // Summary visible, body hidden until expanded.
  expect(screen.getByTestId("details-toggle")).toHaveTextContent("1 tool call");
  expect(screen.getByTestId("details-toggle")).toHaveTextContent("reasoning");
  expect(screen.queryByTestId("details-body")).toBeNull();

  fireEvent.click(screen.getByTestId("details-toggle"));
  expect(screen.getByTestId("details-body")).toHaveTextContent("web_search");
  expect(screen.getByTestId("details-thinking")).toHaveTextContent("because reasons");
});

test("can start expanded", () => {
  render(<MessageDetails steps={STEPS} defaultOpen />);
  expect(screen.getByTestId("details-body")).toHaveTextContent("web_search");
});

test("renders M8 multi-agent / verification kinds + a generic fallback for unknown kinds", () => {
  render(
    <MessageDetails
      defaultOpen
      trace={[
        { kind: "plan", text: "research then verify" },
        { kind: "critique", role: "critic", text: "missing a source" },
        { kind: "verification", verdict: "pass", text: "grounded" },
        // An unknown future kind must still render (generic fallback), not break the UI.
        { kind: "future-kind" as unknown as "plan", text: "hi" },
      ]}
    />,
  );
  expect(screen.getByTestId("details-plan")).toHaveTextContent("research then verify");
  expect(screen.getByTestId("details-critique")).toHaveTextContent("critic");
  expect(screen.getByTestId("details-verification")).toHaveTextContent("pass");
  expect(screen.getByTestId("details-other")).toHaveTextContent("future-kind");
});

test("labels the researcher's block with a 'Researcher' header in the multi-agent trace", () => {
  render(
    <MessageDetails
      defaultOpen
      trace={[
        { kind: "plan", text: "do the thing" },
        // The researcher's reasoning/tool steps follow the planner -> get a "Researcher" header.
        { kind: "reasoning", text: "let me search" },
        { kind: "tool_call", tool: "web_search", args: {} },
        { kind: "critique", text: "ok" },
      ]}
    />,
  );
  expect(screen.getByTestId("details-researcher")).toHaveTextContent("Researcher");
});

test("single-agent reasoning has no Researcher header (no planner/critic boundary)", () => {
  render(<MessageDetails defaultOpen trace={[{ kind: "reasoning", text: "thinking..." }]} />);
  expect(screen.queryByTestId("details-researcher")).toBeNull();
});


test("shows a 'jump to latest' affordance only when the user has scrolled up", () => {
  render(<MessageDetails steps={STEPS} thinking="x" defaultOpen />);
  const body = screen.getByTestId("details-body");
  // jsdom has no layout, so fake the scroll geometry. At the bottom -> no jump button.
  Object.defineProperty(body, "scrollHeight", { value: 500, configurable: true });
  Object.defineProperty(body, "clientHeight", { value: 200, configurable: true });
  Object.defineProperty(body, "scrollTop", { value: 300, writable: true }); // 500-300-200=0
  fireEvent.scroll(body);
  expect(screen.queryByTestId("details-jump")).toBeNull();

  // User scrolls up -> the affordance appears.
  (body as HTMLElement).scrollTop = 0; // 500-0-200=300px from bottom
  fireEvent.scroll(body);
  expect(screen.getByTestId("details-jump")).toBeInTheDocument();

  // Clicking it returns to the bottom and hides the affordance again.
  fireEvent.click(screen.getByTestId("details-jump"));
  expect(screen.queryByTestId("details-jump")).toBeNull();
});

test("pairs a tool_call with its tool_result into a single ToolIO (one row per interaction)", () => {
  render(
    <MessageDetails
      defaultOpen
      trace={[
        { kind: "tool_call", tool: "web_search", args: { query: "x" } },
        { kind: "tool_result", tool: "web_search", ok: true, output: { results: [] } },
      ]}
    />,
  );
  // One ToolIO for the call+result pair, not two separate rows.
  expect(screen.getAllByTestId("toolio")).toHaveLength(1);
  const summary = screen.getByTestId("toolio-summary");
  expect(summary).toHaveTextContent("web_search");
  expect(screen.getByTestId("toolio-status")).toHaveTextContent("ok");
  // Expanding reveals the request + response payloads.
  fireEvent.click(summary);
  expect(screen.getByTestId("toolio-detail")).toHaveTextContent("Response");
});

test("an egress-blocked result keeps the Allow affordance inside the ToolIO", () => {
  const onAllowHost = vi.fn();
  render(
    <MessageDetails
      defaultOpen
      onAllowHost={onAllowHost}
      trace={[
        { kind: "tool_call", tool: "fetch", args: { url: "http://x" } },
        {
          kind: "tool_result",
          tool: "fetch",
          ok: false,
          error: "egress blocked: host 'example.com' is not in the egress allowlist",
        },
      ]}
    />,
  );
  // The pending egress block auto-expands the ToolIO; the Allow button is visible without a click.
  fireEvent.click(screen.getByTestId("egress-allow-btn"));
  expect(onAllowHost).toHaveBeenCalledWith("example.com");
  expect(screen.getByTestId("egress-allowed")).toHaveTextContent("example.com");
});

test("renders the draft answer highlighted; an earlier draft is dimmed as superseded (#393)", () => {
  render(
    <MessageDetails
      defaultOpen
      trace={[
        { kind: "draft", text: "first try at the answer", attempt: 1 },
        { kind: "critique", text: "revise: missing detail" },
        { kind: "draft", text: "the final proposed answer", attempt: 2 },
      ]}
    />,
  );
  const drafts = screen.getAllByTestId("details-draft");
  expect(drafts).toHaveLength(2);
  // Both labeled "Draft answer"; the latest shows its text, the earlier one is marked superseded.
  expect(drafts[0]).toHaveTextContent("Draft answer");
  expect(drafts[0]).toHaveTextContent("superseded");
  expect(drafts[1]).toHaveTextContent("the final proposed answer");
  expect(drafts[1]).not.toHaveTextContent("superseded");
});

test("renders an ordered trace: reasoning, tool call, more reasoning", () => {
  render(
    <MessageDetails
      defaultOpen
      trace={[
        { kind: "reasoning", text: "first I think" },
        { kind: "tool_call", tool: "web_search", args: { query: "x" } },
        { kind: "tool_result", tool: "web_search", ok: true },
        { kind: "reasoning", text: "now I conclude" },
      ]}
    />,
  );
  const text = screen.getByTestId("details-body").textContent ?? "";
  // Order is preserved: reasoning before the tool call, and more reasoning after it.
  expect(text.indexOf("first I think")).toBeLessThan(text.indexOf("web_search"));
  expect(text.indexOf("web_search")).toBeLessThan(text.indexOf("now I conclude"));
});
