import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { ContextMeter } from "./ContextMeter";

test("shows fill percentage and bar when a context limit is known", () => {
  render(
    <ContextMeter
      context={null}
      usage={{
        prompt_tokens: 8192,
        completion_tokens: 100,
        total_tokens: 8292,
        context_limit: 32768,
        elapsed_ms: 2300,
      }}
    />,
  );
  expect(screen.getByTestId("context-meter-label")).toHaveTextContent("8,192 / 32,768 (25%)");
  expect(screen.getByTestId("context-meter-label")).toHaveTextContent("+100 reply");
  expect(screen.getByTestId("usage-time")).toHaveTextContent("2.3 s"); // per-turn time
  expect(screen.getByTestId("context-meter-bar")).toBeInTheDocument();
});

test("shows raw tokens without a bar when no limit (remote provider)", () => {
  render(
    <ContextMeter
      context={null}
      usage={{
        prompt_tokens: 500,
        completion_tokens: 20,
        total_tokens: 520,
        context_limit: null,
        elapsed_ms: 820,
      }}
    />,
  );
  expect(screen.getByTestId("context-meter-label")).toHaveTextContent("500 prompt tokens");
  expect(screen.queryByTestId("context-meter-bar")).not.toBeInTheDocument();
});


test("shows per-chat running totals (tokens + time) across turns", () => {
  render(
    <ContextMeter
      context={null}
      usage={{
        prompt_tokens: 100,
        completion_tokens: 50,
        total_tokens: 150,
        context_limit: 32768,
        elapsed_ms: 1200,
      }}
      totals={{ tokens: 8400, ms: 65000, turns: 6 }}
    />,
  );
  const t = screen.getByTestId("chat-totals");
  expect(t).toHaveTextContent("6 turns");
  expect(t).toHaveTextContent("8,400 tokens");
  expect(t).toHaveTextContent("1m 5s"); // 65000 ms formatted
});

test("shows the context composition breakdown", () => {
  render(
    <ContextMeter
      usage={null}
      context={{
        items: [
          { label: "Grounding", count: 1, chars: 400 },
          { label: "Documents", count: 4, chars: 1600 },
        ],
        total_chars: 2000,
      }}
    />,
  );
  const breakdown = screen.getByTestId("context-breakdown");
  expect(breakdown).toHaveTextContent("Grounding");
  expect(breakdown).toHaveTextContent("Documents (4)");
  // Token counts are toggle-gated (hidden by default); reveal them to see the assembled footer.
  fireEvent.click(screen.getByTestId("context-tokens-toggle"));
  expect(breakdown).toHaveTextContent(/Assembled ~\d+ tokens/);
  expect(screen.getAllByTestId("context-item")).toHaveLength(2);
});

test("the composition section collapses and re-expands via the header toggle", () => {
  localStorage.removeItem("personalai_context_open");
  render(
    <ContextMeter
      usage={null}
      context={{ items: [{ label: "Documents", count: 4, chars: 1600 }], total_chars: 1600 }}
    />,
  );
  // Default open: breakdown is visible.
  expect(screen.getByTestId("context-breakdown")).toBeInTheDocument();

  fireEvent.click(screen.getByTestId("context-collapse-toggle"));
  expect(screen.queryByTestId("context-breakdown")).toBeNull();
  expect(localStorage.getItem("personalai_context_open")).toBe("0");

  fireEvent.click(screen.getByTestId("context-collapse-toggle"));
  expect(screen.getByTestId("context-breakdown")).toBeInTheDocument();
  expect(localStorage.getItem("personalai_context_open")).toBe("1");
});

test("an accessible explanation popover opens on click of the '?' info button", () => {
  localStorage.removeItem("personalai_context_open");
  render(
    <ContextMeter
      usage={null}
      context={{ items: [{ label: "Documents", count: 4, chars: 1600 }], total_chars: 1600 }}
    />,
  );
  expect(screen.queryByTestId("context-expl")).toBeNull();
  fireEvent.click(screen.getByTestId("context-help-btn"));
  expect(screen.getByTestId("context-expl")).toHaveTextContent(
    "Passages retrieved from files you uploaded",
  );
  // Toggling off closes it again.
  fireEvent.click(screen.getByTestId("context-help-btn"));
  expect(screen.queryByTestId("context-expl")).toBeNull();
});

test("an unknown source falls back to the generic explanation", () => {
  localStorage.removeItem("personalai_context_open");
  render(
    <ContextMeter
      usage={null}
      context={{ items: [{ label: "Mystery source", count: 1, chars: 100 }], total_chars: 100 }}
    />,
  );
  fireEvent.click(screen.getByTestId("context-help-btn"));
  expect(screen.getByTestId("context-expl")).toHaveTextContent("Included in the prompt for this turn.");
});

test("shows a token overlay when hovering a context category", () => {
  render(
    <ContextMeter
      usage={null}
      context={{ items: [{ label: "Documents", count: 4, chars: 1600 }], total_chars: 1600 }}
    />,
  );
  expect(screen.queryByTestId("context-tooltip")).toBeNull();
  fireEvent.mouseEnter(screen.getByTestId("context-item"));
  const tip = screen.getByTestId("context-tooltip");
  expect(tip).toHaveTextContent(/tokens/);
  expect(tip).toHaveTextContent("1,600 chars");
  fireEvent.mouseLeave(screen.getByTestId("context-item"));
  expect(screen.queryByTestId("context-tooltip")).toBeNull();
});
