import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { ContextMeter } from "./ContextMeter";

test("shows fill percentage and bar when a context limit is known", () => {
  render(
    <ContextMeter
      usage={{ prompt_tokens: 8192, completion_tokens: 100, total_tokens: 8292, context_limit: 32768 }}
    />,
  );
  expect(screen.getByTestId("context-meter-label")).toHaveTextContent("8,192 / 32,768 (25%)");
  expect(screen.getByTestId("context-meter-label")).toHaveTextContent("+100 reply");
  expect(screen.getByTestId("context-meter-bar")).toBeInTheDocument();
});

test("shows raw tokens without a bar when no limit (remote provider)", () => {
  render(
    <ContextMeter
      usage={{ prompt_tokens: 500, completion_tokens: 20, total_tokens: 520, context_limit: null }}
    />,
  );
  expect(screen.getByTestId("context-meter-label")).toHaveTextContent("500 prompt tokens");
  expect(screen.queryByTestId("context-meter-bar")).not.toBeInTheDocument();
});
