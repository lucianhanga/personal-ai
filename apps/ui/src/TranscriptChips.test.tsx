import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { TranscriptAudio } from "./AudioChips";
import { TranscriptDocuments } from "./DocumentChips";

// A controllable clipboard so we can assert what the Copy button actually copies (#426 scenario 2).
const writeText = vi.fn().mockResolvedValue(undefined);
beforeEach(() => {
  writeText.mockClear();
  Object.assign(navigator, { clipboard: { writeText } });
});

// --- TranscriptDocuments -------------------------------------------------------------------------

test("renders a read-only doc chip with name + snippet, NO remove control", () => {
  render(<TranscriptDocuments documents={[{ name: "contract.pdf", text: "This Agreement is made." }]} />);
  const chip = screen.getByTestId("document-attachment");
  expect(chip).toHaveTextContent("contract.pdf");
  expect(chip).toHaveAttribute("data-status", "sent");
  expect(chip).toHaveAttribute("tabindex", "0");
  // Read-only: no remove button (transcript chips are never removable).
  expect(within(chip).queryByRole("button", { name: /remove/i })).toBeNull();
});

test("scenario 2: clicking a doc chip opens the panel; Copy copies the FULL text", () => {
  const full = "This Agreement is made on the 1st of January, in full.";
  render(<TranscriptDocuments documents={[{ name: "contract.pdf", text: full }]} />);
  fireEvent.click(screen.getByTestId("document-attachment"));
  const panel = screen.getByTestId("document-panel");
  expect(panel).toHaveTextContent(full);
  expect(panel).toHaveAttribute("role", "dialog");
  fireEvent.click(within(panel).getByRole("button", { name: /copy/i }));
  expect(writeText).toHaveBeenCalledWith(full); // full text regardless of the clipped chip snippet
});

test("scenario 2: hover and focus also open the doc panel", () => {
  render(<TranscriptDocuments documents={[{ name: "a.txt", text: "hello world" }]} />);
  const chip = screen.getByTestId("document-attachment");
  fireEvent.mouseEnter(chip);
  expect(screen.getByTestId("document-panel")).toBeInTheDocument();
  fireEvent.click(chip); // re-toggle closed
  expect(screen.queryByTestId("document-panel")).toBeNull();
  fireEvent.focus(chip);
  expect(screen.getByTestId("document-panel")).toBeInTheDocument();
});

test("scenario 3: Escape and click-away both dismiss the doc panel", () => {
  render(<TranscriptDocuments documents={[{ name: "a.txt", text: "x" }]} />);
  const chip = screen.getByTestId("document-attachment");
  fireEvent.click(chip);
  expect(screen.getByTestId("document-panel")).toBeInTheDocument();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByTestId("document-panel")).toBeNull();

  fireEvent.click(chip);
  expect(screen.getByTestId("document-panel")).toBeInTheDocument();
  fireEvent.mouseDown(document.body); // click-away
  expect(screen.queryByTestId("document-panel")).toBeNull();
});

test("scenario 7: many doc chips render and very long text is bounded by the scrolling panel", () => {
  const long = "lorem ipsum ".repeat(2000);
  const docs = Array.from({ length: 6 }, (_, i) => ({ name: `doc${i}.txt`, text: long }));
  render(<TranscriptDocuments documents={docs} />);
  expect(screen.getAllByTestId("document-attachment")).toHaveLength(6);
  fireEvent.click(screen.getAllByTestId("document-attachment")[0]);
  const body = screen.getByTestId("document-panel").querySelector("div:last-child") as HTMLElement;
  // The panel body is bounded + scrollable so long text never grows the bubble.
  expect(body).toHaveStyle({ maxHeight: "14em", overflow: "auto" });
});

test("renders nothing when there are no documents", () => {
  const { container } = render(<TranscriptDocuments documents={[]} />);
  expect(container).toBeEmptyDOMElement();
});

// --- TranscriptAudio -----------------------------------------------------------------------------

test("renders a read-only audio chip with name + snippet, NO remove control", () => {
  render(<TranscriptAudio audio={[{ name: "call.m4a", transcript: "so about the deadline" }]} />);
  const chip = screen.getByTestId("audio-attachment");
  expect(chip).toHaveTextContent("call.m4a");
  expect(chip).toHaveAttribute("data-status", "sent");
  expect(within(chip).queryByRole("button", { name: /remove/i })).toBeNull();
});

test("scenario 2: clicking an audio chip opens the panel; Copy copies the FULL transcript", () => {
  const full = "so about the deadline, we need to ship by Friday at the latest.";
  render(<TranscriptAudio audio={[{ name: "call.m4a", transcript: full }]} />);
  fireEvent.click(screen.getByTestId("audio-attachment"));
  const panel = screen.getByTestId("audio-panel");
  expect(panel).toHaveTextContent(full);
  fireEvent.click(within(panel).getByRole("button", { name: /copy/i }));
  expect(writeText).toHaveBeenCalledWith(full);
});

test("scenario 3: Escape dismisses the audio panel", () => {
  render(<TranscriptAudio audio={[{ name: "a.m4a", transcript: "hi" }]} />);
  fireEvent.click(screen.getByTestId("audio-attachment"));
  expect(screen.getByTestId("audio-panel")).toBeInTheDocument();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByTestId("audio-panel")).toBeNull();
});

test("renders nothing when there is no audio", () => {
  const { container } = render(<TranscriptAudio audio={[]} />);
  expect(container).toBeEmptyDOMElement();
});
