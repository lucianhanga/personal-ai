import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  // Token counts are toggle-gated (hidden by default); reveal them to see the assembled footer.
  fireEvent.click(screen.getByTestId("context-tokens-toggle"));
  expect(breakdown).toHaveTextContent(/Assembled ~\d+ tokens/);
  expect(screen.getAllByTestId("context-item")).toHaveLength(2);
});

test("token counts are hidden by default and the toggle reveals per-source + assembled totals", () => {
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
  // Default: hidden — no per-source "~N tok" and no assembled footer.
  expect(breakdown).not.toHaveTextContent(/~\d+ tok/);
  expect(breakdown).not.toHaveTextContent(/Assembled ~\d+ tokens/);

  const toggle = screen.getByTestId("context-tokens-toggle");
  expect(toggle).toHaveAttribute("aria-pressed", "false");

  // On: per-source counts + the assembled total appear.
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-pressed", "true");
  expect(breakdown).toHaveTextContent(/~\d+ tok/);
  expect(breakdown).toHaveTextContent(/Assembled ~\d+ tokens/);

  // Off again: both hidden.
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-pressed", "false");
  expect(breakdown).not.toHaveTextContent(/~\d+ tok/);
  expect(breakdown).not.toHaveTextContent(/Assembled ~\d+ tokens/);
});

test("the tokens toggle reveals the actual token pieces of a source's text (#391)", async () => {
  render(
    <ContextComposition
      context={{
        items: [{ label: "Documents", count: 1, chars: 16, text: "hello tokenized world" }],
        total_chars: 16,
      }}
    />,
  );
  // Hidden by default.
  expect(screen.queryByTestId("context-tokens")).toBeNull();
  fireEvent.click(screen.getByTestId("context-tokens-toggle"));
  const tokens = screen.getByTestId("context-tokens");
  // The tokenizer is lazy-loaded (dynamic import), so the count + chips appear after it resolves.
  await waitFor(() => expect(tokens).toHaveTextContent(/\d+ tokens · approx \(GPT-style\)/));
  // The text is split into multiple token chips (more than one span beyond the header line).
  const chips = tokens.querySelectorAll("span");
  expect(chips.length).toBeGreaterThan(1);
  // The pieces reconstruct the source text.
  expect(tokens).toHaveTextContent("hello");
  expect(tokens).toHaveTextContent("world");
});

test("the token view is absent for a source without text (pre-#391 turns)", () => {
  render(
    <ContextComposition
      context={{ items: [{ label: "Memory", count: 1, chars: 100 }], total_chars: 100 }}
    />,
  );
  fireEvent.click(screen.getByTestId("context-tokens-toggle"));
  expect(screen.queryByTestId("context-tokens")).toBeNull(); // no text -> no chips
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
