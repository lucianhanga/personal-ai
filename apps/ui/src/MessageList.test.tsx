import { render, screen } from "@testing-library/react";
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
