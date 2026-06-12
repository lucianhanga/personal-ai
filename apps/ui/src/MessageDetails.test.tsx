import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

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
