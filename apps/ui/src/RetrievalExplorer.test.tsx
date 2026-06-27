import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { RetrievalExplorer } from "./RetrievalExplorer";
import * as api from "./api";

afterEach(() => vi.restoreAllMocks());

function passage(rank: number, score: number, name: string, text = "snippet"): api.RetrievedPassage {
  return {
    rank,
    score,
    text,
    source_id: `doc-${rank}`,
    locator: `p.${rank}`,
    name,
    source_kind: "vector",
  };
}

function result(passages: api.RetrievedPassage[]): api.RetrievalResult {
  return { query: "q", scope: "global", top_k: 8, ms: 42, passages };
}

test("renders the idle state before any query is run", () => {
  render(<RetrievalExplorer token="demo" />);
  expect(screen.getByTestId("retrieval-idle")).toBeInTheDocument();
  expect(screen.queryByTestId("retrieval-results")).toBeNull();
  // Run is disabled with an empty query.
  expect(screen.getByTestId("retrieval-run")).toBeDisabled();
});

test("runs a query and shows ranked passages with provenance", async () => {
  vi.spyOn(api, "retrievePassages").mockResolvedValue(
    result([passage(1, 0.9, "Alpha.pdf"), passage(2, 0.45, "Beta.pdf")]),
  );
  render(<RetrievalExplorer token="demo" />);

  fireEvent.change(screen.getByTestId("retrieval-query"), { target: { value: "neural nets" } });
  fireEvent.click(screen.getByTestId("retrieval-run"));

  await waitFor(() => expect(screen.getByTestId("retrieval-results")).toBeInTheDocument());

  const rows = screen.getAllByTestId("retrieval-passage");
  expect(rows).toHaveLength(2);
  // Rank is the primary signal, rendered per row.
  expect(rows[0]).toHaveAttribute("data-rank", "1");
  expect(within(rows[0]).getByTestId("retrieval-rank")).toHaveTextContent("#1");
  // Provenance: source name + locator + source kind.
  expect(within(rows[0]).getByTestId("retrieval-provenance")).toHaveTextContent("Alpha.pdf");
  expect(within(rows[0]).getByTestId("retrieval-provenance")).toHaveTextContent("p.1");
  expect(within(rows[0]).getByTestId("retrieval-source-kind")).toHaveTextContent("vector");
  // Score is exposed as an accessible numeric text equivalent, not just a bar.
  expect(within(rows[0]).getByTestId("retrieval-score")).toHaveTextContent("0.900");

  expect(api.retrievePassages).toHaveBeenCalledWith("demo", "neural nets", 8);
});

test("runs on Enter (form submit), not on keystroke", async () => {
  const spy = vi.spyOn(api, "retrievePassages").mockResolvedValue(result([passage(1, 0.5, "Doc.pdf")]));
  render(<RetrievalExplorer token="demo" />);

  const input = screen.getByTestId("retrieval-query");
  fireEvent.change(input, { target: { value: "hello" } });
  // Typing alone must NOT trigger a backend call.
  expect(spy).not.toHaveBeenCalled();

  fireEvent.submit(screen.getByTestId("retrieval-form"));
  await waitFor(() => expect(screen.getByTestId("retrieval-results")).toBeInTheDocument());
  expect(spy).toHaveBeenCalledTimes(1);
});

test("treats zero passages as a neutral empty signal, not an error", async () => {
  vi.spyOn(api, "retrievePassages").mockResolvedValue(result([]));
  render(<RetrievalExplorer token="demo" />);

  fireEvent.change(screen.getByTestId("retrieval-query"), { target: { value: "nothing" } });
  fireEvent.click(screen.getByTestId("retrieval-run"));

  await waitFor(() => expect(screen.getByTestId("retrieval-empty")).toBeInTheDocument());
  // Neutral — no error alert.
  expect(screen.queryByTestId("retrieval-error")).toBeNull();
});

test("shows an error with Retry that preserves the query and re-runs", async () => {
  const spy = vi
    .spyOn(api, "retrievePassages")
    .mockRejectedValueOnce(new Error("retrieve failed: 503"))
    .mockResolvedValueOnce(result([passage(1, 0.8, "Doc.pdf")]));
  render(<RetrievalExplorer token="demo" />);

  const input = screen.getByTestId("retrieval-query") as HTMLInputElement;
  fireEvent.change(input, { target: { value: "resilient" } });
  fireEvent.click(screen.getByTestId("retrieval-run"));

  await waitFor(() => expect(screen.getByTestId("retrieval-error")).toBeInTheDocument());
  // The query is preserved so the user can re-run it.
  expect(input.value).toBe("resilient");

  fireEvent.click(screen.getByTestId("retrieval-retry"));
  await waitFor(() => expect(screen.getByTestId("retrieval-results")).toBeInTheDocument());
  expect(spy).toHaveBeenCalledTimes(2);
  expect(spy).toHaveBeenLastCalledWith("demo", "resilient", 8);
});

test("disables Run while a retrieval is in flight", async () => {
  let resolve!: (r: api.RetrievalResult) => void;
  vi.spyOn(api, "retrievePassages").mockReturnValue(
    new Promise<api.RetrievalResult>((r) => {
      resolve = r;
    }),
  );
  render(<RetrievalExplorer token="demo" />);

  fireEvent.change(screen.getByTestId("retrieval-query"), { target: { value: "inflight" } });
  fireEvent.click(screen.getByTestId("retrieval-run"));

  await waitFor(() => expect(screen.getByTestId("retrieval-loading")).toBeInTheDocument());
  const run = screen.getByTestId("retrieval-run");
  expect(run).toBeDisabled();
  expect(run).toHaveTextContent("Running…");

  resolve(result([passage(1, 0.7, "Doc.pdf")]));
  await waitFor(() => expect(screen.getByTestId("retrieval-results")).toBeInTheDocument());
  expect(screen.getByTestId("retrieval-run")).not.toBeDisabled();
});

test("expands a long passage snippet on demand", async () => {
  const longText = "x".repeat(400);
  vi.spyOn(api, "retrievePassages").mockResolvedValue(result([passage(1, 0.6, "Doc.pdf", longText)]));
  render(<RetrievalExplorer token="demo" />);

  fireEvent.change(screen.getByTestId("retrieval-query"), { target: { value: "long" } });
  fireEvent.click(screen.getByTestId("retrieval-run"));

  await waitFor(() => expect(screen.getByTestId("retrieval-results")).toBeInTheDocument());
  const text = screen.getByTestId("retrieval-text");
  expect(text.textContent ?? "").toContain("…");
  expect((text.textContent ?? "").length).toBeLessThan(longText.length);

  fireEvent.click(screen.getByTestId("retrieval-expand"));
  expect(screen.getByTestId("retrieval-text")).toHaveTextContent(longText);
});
