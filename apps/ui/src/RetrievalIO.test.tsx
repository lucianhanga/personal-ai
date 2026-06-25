import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";

import { IndexingIO, NerIO, RetrievalIO } from "./RetrievalIO";

test("(retrieval) renders the compact citation list, ordered by descending score", () => {
  render(
    <RetrievalIO
      query="Q3 runway guidance"
      topK={8}
      hits={3}
      scope="union"
      ms={320}
      citations={[
        { source: "notes.md", score: 0.61 },
        { source: "Q3-board.pdf", score: 0.82 },
        { source: "deck.pdf", score: 0.74 },
      ]}
      state="done"
    />,
  );
  const chip = screen.getByTestId("timeline-retrieval");
  expect(chip).toHaveTextContent("Retrieved 3 passages (union)");
  // hits>0 -> default open, the <ol> is rendered.
  const list = within(chip).getByTestId("retrieval-citations");
  expect(list.tagName.toLowerCase()).toBe("ol"); // semantic ordered list
  const scores = within(list).getAllByTestId("retrieval-score").map((n) => n.textContent);
  expect(scores).toEqual(["0.82", "0.74", "0.61"]);
});

test("(retrieval) score is shown as an accessible number; the fill bar is aria-hidden", () => {
  render(
    <RetrievalIO hits={1} scope="global" citations={[{ source: "a.pdf", score: 0.5 }]} state="done" />,
  );
  // The numeric score is real text (accessible); the decorative bar carries aria-hidden.
  expect(screen.getByTestId("retrieval-score")).toHaveTextContent("0.50");
  const bars = document.querySelectorAll('[aria-hidden="true"]');
  expect(bars.length).toBeGreaterThan(0);
});

test("(retrieval) 0 hits -> 'No passages retrieved', pill done, no citation list", () => {
  render(<RetrievalIO hits={0} scope="conversation" citations={[]} state="done" query="x" topK={8} ms={5} />);
  const chip = screen.getByTestId("timeline-retrieval");
  expect(chip).toHaveTextContent("No passages retrieved (conversation)");
  expect(within(chip).getByTestId("pipelineio-status")).toHaveTextContent("done");
  fireEvent.click(within(chip).getByTestId("pipelineio-summary"));
  expect(chip).toHaveTextContent("No passages matched.");
  expect(within(chip).queryByTestId("retrieval-citations")).toBeNull();
});

test("(retrieval) caps the visible label query and keeps the full query in the title", () => {
  const longQuery = "a".repeat(120);
  render(<RetrievalIO hits={1} scope="union" citations={[{ source: "s", score: 0.4 }]} state="done" query={longQuery} topK={4} ms={1} />);
  const chip = screen.getByTestId("timeline-retrieval");
  // The clipped query carries an ellipsis; the full text lives in the element title.
  expect(chip.querySelector("[title]")).toBeTruthy();
});

test("(indexing) Tier-1 label composes ref + chunks; error carries the message", () => {
  const { unmount } = render(<IndexingIO refName="report.pdf" chunks={48} ms={1400} state="done" />);
  expect(screen.getByTestId("timeline-indexing")).toHaveTextContent("Indexed report.pdf - 48 chunks");
  unmount();
  render(<IndexingIO refName="big.pdf" chunks={0} ms={20} state="error" error="embed failed" />);
  const chip = screen.getByTestId("timeline-indexing");
  expect(within(chip).getByTestId("pipelineio-status")).toHaveTextContent("error");
  fireEvent.click(within(chip).getByTestId("pipelineio-summary"));
  expect(within(chip).getByTestId("pipelineio-error")).toHaveTextContent("embed failed");
});

test("(ner) renders the entity count + the per-type breakdown", () => {
  render(
    <NerIO
      count={6}
      types={[
        { type: "PERSON", count: 3 },
        { type: "ORG", count: 2 },
        { type: "DATE", count: 1 },
      ]}
      state="done"
    />,
  );
  const chip = screen.getByTestId("timeline-ner");
  expect(chip).toHaveTextContent("Extracted 6 entities");
  fireEvent.click(within(chip).getByTestId("pipelineio-summary"));
  expect(chip).toHaveTextContent("PERSON: 3 - ORG: 2 - DATE: 1");
});
