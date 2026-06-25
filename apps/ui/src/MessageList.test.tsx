import { fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { expect, test, vi } from "vitest";

import type { ChatMessage } from "./api";
import { MessageList, type CopyPayload } from "./MessageList";

function renderList(
  messages: ChatMessage[],
  opts: {
    busy?: boolean;
    liveStopped?: boolean;
    onCopyToComposer?: (p: CopyPayload) => void;
    onEditResubmit?: (id: number, text: string) => void;
    onDelete?: (id: number) => void;
  } = {},
) {
  return render(
    <MessageList
      messages={messages}
      trace={{}}
      citations={{}}
      busy={opts.busy ?? false}
      ttsEnabled={false}
      listRef={createRef<HTMLDivElement>()}
      onScroll={() => {}}
      liveStopped={opts.liveStopped}
      onCopyToComposer={opts.onCopyToComposer}
      onEditResubmit={opts.onEditResubmit}
      onDelete={opts.onDelete}
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

test("collapsing a question folds the whole turn: the following assistant answer is hidden", () => {
  renderList([
    { role: "user", content: "What is the capital of France?" },
    { role: "assistant", content: "The capital of France is Paris." },
  ]);

  // Expanded by default: the assistant answer is visible.
  expect(screen.getByTestId("msg-assistant")).toHaveTextContent("The capital of France is Paris.");

  // Collapse the question: the question preview shows, the whole assistant turn is hidden.
  fireEvent.click(screen.getByTestId("question-toggle"));
  expect(screen.getByTestId("msg-user")).toHaveTextContent("What is the capital of France?");
  expect(screen.queryByTestId("msg-assistant")).toBeNull();

  // Expand again: the assistant answer returns.
  fireEvent.click(screen.getByTestId("question-toggle"));
  expect(screen.getByTestId("msg-assistant")).toHaveTextContent("The capital of France is Paris.");
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

// --- #426: sent-message attachment presentation (display-vs-model split) -------------------------

test("scenario 1: bubble shows the typed prompt + image/doc/audio chips, NOT the folded content", () => {
  // The model-facing folded content carries the bracketed blocks; the bubble must show only the
  // original typed prompt (displayContent) plus the chip strip — never the [Document:]/[Audio:] text.
  const folded =
    "Summarize the contract\n\n[Audio: call.m4a]\nso about the deadline\n\n[Document: contract.pdf]\nThis Agreement is made on the 1st of January.";
  renderList([
    {
      role: "user",
      content: folded,
      displayContent: "Summarize the contract",
      images: ["data:image/png;base64,AAAA"],
      image_descriptions: ["a signed page"],
      documents: [{ name: "contract.pdf", text: "This Agreement is made on the 1st of January." }],
      audio: [{ name: "call.m4a", transcript: "so about the deadline" }],
    },
    { role: "assistant", content: "ok" },
  ]);
  const bubble = screen.getByTestId("msg-user");
  expect(bubble).toHaveTextContent("Summarize the contract");
  // None of the fold markers / folded payload leak into the bubble.
  expect(bubble).not.toHaveTextContent("[Document:");
  expect(bubble).not.toHaveTextContent("[Audio:");
  expect(bubble).not.toHaveTextContent("This Agreement is made on the 1st of January.");
  // All three chip rows render, in order.
  expect(screen.getByTestId("msg-images")).toBeInTheDocument();
  expect(screen.getByTestId("msg-documents")).toBeInTheDocument();
  expect(screen.getByTestId("msg-audio")).toBeInTheDocument();
});

test("scenario 4: a reloaded turn renders identically from structured fields (no fold leak)", () => {
  // What fetchConversation produces on reload: displayContent + documents + audio (no folded leak).
  renderList([
    {
      role: "user",
      content: "Summarize\n\n[Document: a.txt]\nfull text here",
      displayContent: "Summarize",
      documents: [{ name: "a.txt", text: "full text here" }],
    },
  ]);
  const bubble = screen.getByTestId("msg-user");
  expect(bubble).toHaveTextContent("Summarize");
  expect(bubble).not.toHaveTextContent("[Document:");
  expect(screen.getByTestId("msg-documents")).toHaveTextContent("a.txt");
});

test("scenario 5: a legacy folded turn (no structural meta) renders content verbatim", () => {
  // Old turns have only folded `content` — no displayContent/documents/audio. They must render the
  // content exactly as before (backward-compat), with no chip strip.
  const legacy = "Old question\n\n[Document: legacy.pdf]\nsome extracted text";
  renderList([{ role: "user", content: legacy }]);
  const bubble = screen.getByTestId("msg-user");
  // Verbatim: the fold markers are still shown (we do NOT retro-parse them into chips).
  expect(bubble).toHaveTextContent("[Document: legacy.pdf]");
  expect(screen.queryByTestId("msg-documents")).toBeNull();
  expect(screen.queryByTestId("msg-audio")).toBeNull();
});

test("scenario 6: an attachments-only turn renders no empty bubble line, just the chip strip", () => {
  // No typed text -> displayContent is "" -> the bubble shows the "You:" label + chips, no stray line.
  renderList([
    {
      role: "user",
      content: "[Image: a cat]",
      displayContent: "",
      images: ["data:image/png;base64,AAAA"],
      image_descriptions: ["a cat"],
    },
  ]);
  const bubble = screen.getByTestId("msg-user");
  expect(bubble).toHaveTextContent("You:");
  expect(bubble).not.toHaveTextContent("[Image:");
  expect(screen.getByTestId("msg-images")).toBeInTheDocument();
});

test("displayContent takes precedence over content; absent displayContent falls back to content", () => {
  renderList([
    { role: "user", content: "FOLDED", displayContent: "typed prompt" },
    { role: "user", content: "verbatim legacy" },
  ]);
  const bubbles = screen.getAllByTestId("msg-user");
  expect(bubbles[0]).toHaveTextContent("typed prompt");
  expect(bubbles[0]).not.toHaveTextContent("FOLDED");
  expect(bubbles[1]).toHaveTextContent("verbatim legacy");
});

test("collapsing a structural turn hides the chip strip and shows the prompt preview", () => {
  renderList([
    {
      role: "user",
      content: "folded",
      displayContent: "Review the deck",
      documents: [{ name: "deck.pdf", text: "slide one" }],
    },
    { role: "assistant", content: "done" },
  ]);
  expect(screen.getByTestId("msg-documents")).toBeInTheDocument();
  fireEvent.click(screen.getByTestId("question-toggle"));
  // Collapsed: preview of the prompt (not content), chips gone.
  expect(screen.getByTestId("msg-user")).toHaveTextContent("Review the deck");
  expect(screen.queryByTestId("msg-documents")).toBeNull();
});

// --- #412: the "Generation stopped." marker -----------------------------------------------------

test("a stopped turn (meta.stopped) shows the amber marker, distinct from the error path", () => {
  renderList([
    { role: "user", content: "q" },
    { role: "assistant", content: "The capital of France is Par", meta: { stopped: { by: "user" } } },
  ]);
  const marker = screen.getByTestId("stopped-marker");
  expect(marker).toHaveTextContent("Generation stopped.");
  expect(marker).toHaveStyle({ color: "#b06f00" }); // amber, not red
});

test("a turn stopped before any answer shows the pre-answer marker (no blank bubble)", () => {
  renderList([
    { role: "user", content: "q" },
    { role: "assistant", content: "", meta: { stopped: { by: "user" } } },
  ]);
  expect(screen.getByTestId("stopped-marker")).toHaveTextContent(
    "Generation stopped before an answer was produced.",
  );
});

test("liveStopped shows the marker on the last turn before any reload from meta", () => {
  renderList(
    [
      { role: "user", content: "q" },
      { role: "assistant", content: "partial" }, // no meta yet — live session
    ],
    { liveStopped: true },
  );
  expect(screen.getByTestId("stopped-marker")).toBeInTheDocument();
});

test("a completed turn shows no stopped marker", () => {
  renderList([
    { role: "user", content: "q" },
    { role: "assistant", content: "done" },
  ]);
  expect(screen.queryByTestId("stopped-marker")).toBeNull();
});

// --- #441: per-question Copy / Edit / Delete ----------------------------------------------------

test("each user question has a Copy / Edit / Delete action row with real aria-labels", () => {
  renderList([{ role: "user", id: 5, content: "What is the capital of France?" }]);
  const copy = screen.getByTestId("question-copy-0");
  const edit = screen.getByTestId("question-edit-0");
  const del = screen.getByTestId("question-delete-0");
  expect(copy).toHaveAttribute("aria-label", expect.stringContaining("Copy"));
  expect(edit).toHaveAttribute("aria-label", "Edit question");
  expect(del).toHaveAttribute("aria-label", "Delete question");
  // The delete glyph is red at rest (the only destructive control in the row).
  expect(del).toHaveStyle({ color: "#b00020" });
});

test("Copy loads the question + re-attachable resources and flips to a check", () => {
  const onCopyToComposer = vi.fn();
  renderList(
    [
      {
        role: "user",
        id: 5,
        content: "folded",
        displayContent: "Summarize the contract",
        images: ["data:image/png;base64,AAAA"],
        image_descriptions: ["a page"],
        documents: [{ name: "c.pdf", text: "the contract" }],
        audio: [{ name: "a.m4a", transcript: "the call" }],
      },
    ],
    { onCopyToComposer },
  );
  fireEvent.click(screen.getByTestId("question-copy-0"));
  expect(onCopyToComposer).toHaveBeenCalledTimes(1);
  const payload = onCopyToComposer.mock.calls[0][0] as CopyPayload;
  expect(payload.text).toBe("Summarize the contract");
  expect(payload.images).toEqual(["data:image/png;base64,AAAA"]);
  expect(payload.documents).toEqual([{ name: "c.pdf", text: "the contract" }]);
  expect(payload.audio).toEqual([{ name: "a.m4a", transcript: "the call" }]);
  expect(payload.textOnly).toBe(false);
  // aria-live announces the load with the attachment count (1 image + 1 doc + 1 audio = 3).
  expect(screen.getByTestId("question-announce")).toHaveTextContent(
    "Question and 3 attachment(s) loaded into the composer.",
  );
});

test("Copy on an old turn with no structured resources is flagged text-only", () => {
  const onCopyToComposer = vi.fn();
  renderList([{ role: "user", id: 5, content: "legacy question" }], { onCopyToComposer });
  fireEvent.click(screen.getByTestId("question-copy-0"));
  const payload = onCopyToComposer.mock.calls[0][0] as CopyPayload;
  expect(payload.textOnly).toBe(true);
  expect(payload.text).toBe("legacy question");
});

test("Edit shows the inline textarea, the amber later-turn warning, and Resubmit/Cancel", () => {
  const onEditResubmit = vi.fn();
  renderList(
    [
      { role: "user", id: 5, content: "first" },
      { role: "assistant", content: "a1" },
      { role: "user", id: 7, content: "second" },
      { role: "assistant", content: "a2" },
    ],
    { onEditResubmit },
  );
  // Edit the FIRST question (one later turn follows).
  fireEvent.click(screen.getByTestId("question-edit-0"));
  expect(screen.getByTestId("question-edit-input")).toHaveValue("first");
  expect(screen.getByTestId("edit-warning")).toHaveTextContent("discard 1 later turn");
  fireEvent.change(screen.getByTestId("question-edit-input"), { target: { value: "first edited" } });
  fireEvent.click(screen.getByTestId("edit-resubmit"));
  expect(onEditResubmit).toHaveBeenCalledWith(5, "first edited");
});

test("Edit on the latest question shows the softened warning (no later-turns language)", () => {
  renderList(
    [
      { role: "user", id: 9, content: "latest" },
      { role: "assistant", content: "a" },
    ],
    { onEditResubmit: vi.fn() },
  );
  fireEvent.click(screen.getByTestId("question-edit-0"));
  expect(screen.getByTestId("edit-warning")).toHaveTextContent(
    "Re-running this question will replace its current answer.",
  );
  expect(screen.getByTestId("edit-warning")).not.toHaveTextContent("later turn");
});

test("empty edit with no resources disables Resubmit; a resource re-enables it", () => {
  renderList([{ role: "user", id: 9, content: "x" }], { onEditResubmit: vi.fn() });
  fireEvent.click(screen.getByTestId("question-edit-0"));
  fireEvent.change(screen.getByTestId("question-edit-input"), { target: { value: "   " } });
  expect(screen.getByTestId("edit-resubmit")).toBeDisabled();
  expect(screen.getByTestId("edit-empty-hint")).toBeInTheDocument();
});

test("Delete opens an inline confirm (Cancel focused) and confirming truncates from this turn", () => {
  const onDelete = vi.fn();
  renderList(
    [
      { role: "user", id: 5, content: "first" },
      { role: "assistant", content: "a1" },
      { role: "user", id: 7, content: "second" },
      { role: "assistant", content: "a2" },
    ],
    { onDelete },
  );
  fireEvent.click(screen.getByTestId("question-delete-0"));
  const confirm = screen.getByTestId("delete-confirm");
  expect(confirm).toHaveTextContent("removes 1 later turn(s)");
  expect(screen.getByTestId("delete-confirm-cancel")).toHaveFocus(); // accidental Enter cancels
  fireEvent.click(screen.getByTestId("delete-confirm-yes"));
  expect(onDelete).toHaveBeenCalledWith(5);
});

test("Delete on the latest question uses softened copy (no 'everything after it')", () => {
  renderList(
    [
      { role: "user", id: 9, content: "only" },
      { role: "assistant", content: "a" },
    ],
    { onDelete: vi.fn() },
  );
  fireEvent.click(screen.getByTestId("question-delete-0"));
  expect(screen.getByTestId("delete-confirm")).toHaveTextContent(
    "Delete this question and its answer? This can't be undone.",
  );
});

test("while busy, all per-question controls are disabled", () => {
  renderList(
    [
      { role: "user", id: 5, content: "q" },
      { role: "assistant", content: "" },
    ],
    { busy: true, onEditResubmit: vi.fn(), onDelete: vi.fn() },
  );
  expect(screen.getByTestId("question-edit-0")).toBeDisabled();
  expect(screen.getByTestId("question-delete-0")).toBeDisabled();
});

test("Edit/Delete are disabled on an in-flight turn that has no stable id yet", () => {
  // The optimistic just-sent user turn has no backend id -> mutate controls are off.
  renderList([{ role: "user", content: "optimistic" }], { onEditResubmit: vi.fn(), onDelete: vi.fn() });
  expect(screen.getByTestId("question-edit-0")).toBeDisabled();
  expect(screen.getByTestId("question-delete-0")).toBeDisabled();
});
