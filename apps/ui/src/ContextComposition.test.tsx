import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { ContextComposition } from "./ContextComposition";

test("renders a row per source plus the assembled-tokens footer", () => {
  render(
    <ContextComposition
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
  expect(breakdown).toHaveTextContent(/Assembled ~\d+ tokens/);
  expect(screen.getAllByTestId("context-item")).toHaveLength(2);
});

test("the '?' button opens a real-label explanation (not the generic fallback)", () => {
  render(
    <ContextComposition
      context={{ items: [{ label: "Memory", count: 2, chars: 800 }], total_chars: 800 }}
    />,
  );
  expect(screen.queryByTestId("context-expl")).toBeNull();
  fireEvent.click(screen.getByTestId("context-help-btn"));
  expect(screen.getByTestId("context-expl")).toHaveTextContent(
    "Facts saved from past chats that the assistant is allowed to recall.",
  );
  // Toggling off closes it again.
  fireEvent.click(screen.getByTestId("context-help-btn"));
  expect(screen.queryByTestId("context-expl")).toBeNull();
});

test("the real 'Grounding' label resolves to its specific explanation", () => {
  render(
    <ContextComposition
      context={{ items: [{ label: "Grounding", count: 1, chars: 100 }], total_chars: 100 }}
    />,
  );
  fireEvent.click(screen.getByTestId("context-help-btn"));
  expect(screen.getByTestId("context-expl")).toHaveTextContent(
    "An instruction to answer from the provided context and not fabricate facts.",
  );
});

test("an unknown source falls back to the generic explanation", () => {
  render(
    <ContextComposition
      context={{ items: [{ label: "Mystery source", count: 1, chars: 100 }], total_chars: 100 }}
    />,
  );
  fireEvent.click(screen.getByTestId("context-help-btn"));
  expect(screen.getByTestId("context-expl")).toHaveTextContent("Included in the prompt for this turn.");
});

test("without collapsible there is no header toggle and rows are visible", () => {
  render(
    <ContextComposition
      context={{ items: [{ label: "Documents", count: 1, chars: 100 }], total_chars: 100 }}
    />,
  );
  expect(screen.queryByTestId("context-collapse-toggle")).toBeNull();
  expect(screen.getByTestId("context-breakdown")).toBeInTheDocument();
});

test("collapsible persists open/closed state under storageKey", () => {
  const key = "personalai_test_ctx_open";
  localStorage.removeItem(key);
  render(
    <ContextComposition
      context={{ items: [{ label: "Documents", count: 1, chars: 100 }], total_chars: 100 }}
      collapsible
      defaultOpen
      storageKey={key}
    />,
  );
  expect(screen.getByTestId("context-breakdown")).toBeInTheDocument();
  fireEvent.click(screen.getByTestId("context-collapse-toggle"));
  expect(screen.queryByTestId("context-breakdown")).toBeNull();
  expect(localStorage.getItem(key)).toBe("0");
});
