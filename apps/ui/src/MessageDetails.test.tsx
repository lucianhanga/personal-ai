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
