import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import {
  DocumentChips,
  EMPTY_DOC_EXPLANATION,
  type DocumentAttachment,
} from "./DocumentChips";

// A controllable clipboard so we can assert what Copy actually writes.
const writeText = vi.fn().mockResolvedValue(undefined);
beforeEach(() => {
  writeText.mockClear();
  Object.assign(navigator, { clipboard: { writeText } });
});

const chip = (over: Partial<DocumentAttachment> & Pick<DocumentAttachment, "status">): DocumentAttachment => ({
  id: over.id ?? "d1",
  name: over.name ?? "doc.pdf",
  text: over.text ?? "",
  ...over,
});

// --- state cues ----------------------------------------------------------------------------------

test("extracting chip shows the in-progress cue and does NOT open a panel", () => {
  render(<DocumentChips chips={[chip({ status: "extracting" })]} onRemove={() => {}} />);
  const el = screen.getByTestId("document-attachment");
  expect(el).toHaveAttribute("data-status", "extracting");
  expect(el).toHaveTextContent(/extracting/i);
  fireEvent.mouseEnter(el);
  expect(screen.queryByTestId("document-panel")).toBeNull(); // no text yet
});

test("small chip folds inline: shows a snippet, an 'In message' badge, and opens its text panel", () => {
  render(
    <DocumentChips
      chips={[chip({ status: "small", text: "the quick brown fox jumps over the lazy dog" })]}
      onRemove={() => {}}
    />,
  );
  const el = screen.getByTestId("document-attachment");
  expect(el).toHaveAttribute("data-status", "small");
  const badge = screen.getByTestId("document-retrieval-badge");
  expect(badge).toHaveAttribute("data-retrieval", "inline");
  expect(badge).toHaveTextContent(/in message/i);
  fireEvent.click(el);
  expect(screen.getByTestId("document-panel")).toHaveTextContent("the quick brown fox");
});

test("large chip is RAG-ingested: shows the 'Searched in this chat' badge and opens its text panel", () => {
  render(
    <DocumentChips chips={[chip({ status: "large", text: "lorem ipsum ".repeat(50) })]} onRemove={() => {}} />,
  );
  const badge = screen.getByTestId("document-retrieval-badge");
  expect(badge).toHaveAttribute("data-retrieval", "rag");
  expect(badge).toHaveTextContent(/searched in this chat/i);
  fireEvent.click(screen.getByTestId("document-attachment"));
  expect(screen.getByTestId("document-panel")).toBeInTheDocument();
});

test("error chip shows the failure cue (red) and does NOT open a panel", () => {
  render(
    <DocumentChips chips={[chip({ status: "error", error: "extract failed: 500" })]} onRemove={() => {}} />,
  );
  const el = screen.getByTestId("document-attachment");
  expect(el).toHaveAttribute("data-status", "error");
  expect(el).toHaveTextContent("extract failed: 500");
  fireEvent.mouseEnter(el);
  expect(screen.queryByTestId("document-panel")).toBeNull();
});

// --- #446: empty (scanned / image-only PDF) ------------------------------------------------------

test("#446: empty chip shows 'no text found' and NO retrieval badge (not folded, not RAG'd)", () => {
  render(<DocumentChips chips={[chip({ status: "empty", text: "" })]} onRemove={() => {}} />);
  const el = screen.getByTestId("document-attachment");
  expect(el).toHaveAttribute("data-status", "empty");
  expect(el).toHaveTextContent(/no text found/i);
  // Empty docs are neither folded inline nor RAG-ingested, so there is no retrieval badge.
  expect(screen.queryByTestId("document-retrieval-badge")).toBeNull();
});

test("#446: empty chip opens a panel that EXPLAINS the scanned/image-only case, with no Copy", () => {
  render(<DocumentChips chips={[chip({ status: "empty", text: "" })]} onRemove={() => {}} />);
  fireEvent.click(screen.getByTestId("document-attachment"));
  const panel = screen.getByTestId("document-panel");
  expect(panel).toHaveAttribute("role", "dialog");
  expect(screen.getByTestId("document-empty-explanation")).toHaveTextContent(EMPTY_DOC_EXPLANATION);
  // Nothing to copy -> the Copy control is hidden.
  expect(within(panel).queryByRole("button", { name: /copy/i })).toBeNull();
});

test("#446: empty chip is dismissable via Escape and is removable", () => {
  const onRemove = vi.fn();
  render(<DocumentChips chips={[chip({ status: "empty", id: "d9", text: "" })]} onRemove={onRemove} />);
  const el = screen.getByTestId("document-attachment");
  fireEvent.focus(el);
  expect(screen.getByTestId("document-panel")).toBeInTheDocument();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByTestId("document-panel")).toBeNull();
  fireEvent.click(screen.getByTestId("remove-document-d9"));
  expect(onRemove).toHaveBeenCalledWith("d9");
});

// --- copy + remove on a real (small) doc ---------------------------------------------------------

test("Copy in a small-doc panel writes the FULL text, not the clipped snippet", () => {
  const full = "This Agreement is made on the 1st of January and runs in full to the very end.";
  render(<DocumentChips chips={[chip({ status: "small", id: "d2", text: full })]} onRemove={() => {}} />);
  fireEvent.click(screen.getByTestId("document-attachment"));
  fireEvent.click(screen.getByTestId("copy-document-d2"));
  expect(writeText).toHaveBeenCalledWith(full);
});

test("renders nothing when there are no chips", () => {
  const { container } = render(<DocumentChips chips={[]} onRemove={() => {}} />);
  expect(container).toBeEmptyDOMElement();
});
