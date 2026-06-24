import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { ToolIO } from "./ToolIO";

test("tier 1: shows tool name, an arg hint, and a green ok pill; expands to request + response", () => {
  render(
    <ToolIO tool="web_search" args={{ query: "weather in Paris" }} ok output={{ results: [1, 2] }} />,
  );
  // Tier-1 summary line.
  const summary = screen.getByTestId("toolio-summary");
  expect(summary).toHaveTextContent("web_search");
  expect(summary).toHaveTextContent("weather in Paris"); // first string arg as the hint
  expect(screen.getByTestId("toolio-status")).toHaveTextContent("ok");

  // Tier 2 is collapsed by default.
  expect(screen.queryByTestId("toolio-detail")).toBeNull();
  fireEvent.click(summary);
  const detail = screen.getByTestId("toolio-detail");
  expect(detail).toHaveTextContent("Request");
  expect(detail).toHaveTextContent("Response");
  expect(detail).toHaveTextContent("results");
});

test("error result shows a red error pill and the error text (no Response payload)", () => {
  render(<ToolIO tool="fetch" args={{ url: "http://x" }} ok={false} error="boom: blocked" />);
  expect(screen.getByTestId("toolio-status")).toHaveTextContent("error");
  fireEvent.click(screen.getByTestId("toolio-summary"));
  expect(screen.getByTestId("toolio-error")).toHaveTextContent("boom: blocked");
});

test("a call with no result yet shows the 'no result' pill", () => {
  render(<ToolIO tool="fetch" args={{ url: "http://x" }} />);
  expect(screen.getByTestId("toolio-status")).toHaveTextContent("no result");
});

test("the Copy button is present in the request payload once expanded", () => {
  render(<ToolIO tool="t" args={{ a: 1 }} ok output={{ b: 2 }} />);
  fireEvent.click(screen.getByTestId("toolio-summary"));
  expect(screen.getAllByTestId("json-copy").length).toBeGreaterThan(0);
});

test("egress allow-on-deny: Allow fires onAllow, then shows the allowed state", () => {
  const onAllow = vi.fn();
  const { rerender } = render(
    <ToolIO tool="fetch" ok={false} error="egress blocked" host="example.com" onAllow={onAllow} />,
  );
  // A pending egress block auto-expands so the Allow affordance is immediately visible.
  fireEvent.click(screen.getByTestId("egress-allow-btn"));
  expect(onAllow).toHaveBeenCalled();

  // Panel stays open across the rerender; the allowed state replaces the Allow button.
  rerender(
    <ToolIO tool="fetch" ok={false} error="egress blocked" host="example.com" allowed onAllow={onAllow} />,
  );
  expect(screen.getByTestId("egress-allowed")).toHaveTextContent("example.com");
});
