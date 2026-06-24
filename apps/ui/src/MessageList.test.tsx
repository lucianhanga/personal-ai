import { fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { expect, test } from "vitest";

import type { ChatMessage } from "./api";
import { MessageList } from "./MessageList";

function renderList(messages: ChatMessage[]) {
  return render(
    <MessageList
      messages={messages}
      trace={{}}
      citations={{}}
      busy={false}
      ttsEnabled={false}
      listRef={createRef<HTMLDivElement>()}
      onScroll={() => {}}
    />,
  );
}

test("shows a per-message token + time footer from persisted usage", () => {
  renderList([
    { role: "user", content: "hi" },
    {
      role: "assistant",
      content: "hello",
      meta: { usage: { prompt_tokens: 100, completion_tokens: 50, total_tokens: 150, elapsed_ms: 2300 } },
    },
  ]);
  const footer = screen.getByTestId("msg-usage");
  expect(footer).toHaveTextContent("150 tok");
  expect(footer).toHaveTextContent("2.3 s");
  // full split is in the hover title
  expect(footer).toHaveAttribute("title", "100 prompt + 50 reply = 150 tokens in 2.3 s");
});

test("compacts large token counts in the footer", () => {
  renderList([
    {
      role: "assistant",
      content: "x",
      meta: { usage: { prompt_tokens: 11000, completion_tokens: 1000, total_tokens: 12000, elapsed_ms: 500 } },
    },
  ]);
  expect(screen.getByTestId("msg-usage")).toHaveTextContent("12.0k tok");
});

test("renders no footer when a message has no usage", () => {
  renderList([{ role: "assistant", content: "x" }]);
  expect(screen.queryByTestId("msg-usage")).toBeNull();
});

test("shows a per-message context disclosure that reveals the composition when opened", () => {
  renderList([
    {
      role: "assistant",
      content: "hello",
      meta: {
        context: {
          items: [
            { label: "Grounding", count: 1, chars: 400 },
            { label: "Documents", count: 4, chars: 1600 },
          ],
          total_chars: 2000,
        },
      },
    },
  ]);
  const disclosure = screen.getByTestId("msg-context");
  expect(disclosure).toHaveTextContent(/Context \(~\d+ tokens\)/);
  // Collapsed-by-default <details>: the composition renders but is hidden until opened.
  expect(screen.getByTestId("context-breakdown")).toBeInTheDocument();
  fireEvent.click(disclosure.querySelector("summary")!);
  expect(disclosure).toHaveTextContent("Grounding");
  expect(disclosure).toHaveTextContent("Documents (4)");
});

test("renders no context disclosure when a message has no context snapshot", () => {
  renderList([{ role: "assistant", content: "x", meta: { usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2, elapsed_ms: 1 } } }]);
  expect(screen.queryByTestId("msg-context")).toBeNull();
});

test("user questions are collapsible: toggle hides full text + images, shows ellipsized preview", () => {
  const longQuestion =
    "This is a very long user question that exceeds eighty characters so the collapsed preview gets clipped with an ellipsis.";
  renderList([
    { role: "user", content: longQuestion, images: ["data:image/png;base64,AAAA"] },
    { role: "assistant", content: "hello" },
  ]);

  const toggle = screen.getByTestId("question-toggle");
  // Default expanded: full text + images visible, aria-expanded true.
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(toggle).toHaveAttribute("aria-label", "Collapse question");
  expect(screen.getByTestId("msg-user")).toHaveTextContent(longQuestion);
  expect(screen.getByTestId("msg-images")).toBeInTheDocument();

  // Collapse: full text hidden, ellipsized first-80-chars preview shown, images gone.
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(toggle).toHaveAttribute("aria-label", "Expand question");
  const preview = `${longQuestion.slice(0, 80)}…`;
  expect(screen.getByTestId("msg-user")).toHaveTextContent(preview);
  expect(screen.getByTestId("msg-user")).not.toHaveTextContent(longQuestion);
  expect(screen.queryByTestId("msg-images")).toBeNull();

  // Expand again: full text + images back, aria-expanded flips true.
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByTestId("msg-user")).toHaveTextContent(longQuestion);
  expect(screen.getByTestId("msg-images")).toBeInTheDocument();
});

test("user message blocks get a tinted background + left accent border to delimit turns", () => {
  renderList([
    { role: "user", content: "hi" },
    { role: "assistant", content: "hello" },
  ]);
  const user = screen.getByTestId("msg-user");
  // Inline-style tint + accent so each user turn reads as a distinct block.
  expect(user).toHaveStyle({ background: "#eef3fb" });
  expect(user).toHaveStyle({ borderLeft: "3px solid #4a90d9" });
});
