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
