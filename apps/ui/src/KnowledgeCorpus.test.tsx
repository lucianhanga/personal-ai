import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, test, vi } from "vitest";

import { KnowledgeCorpusTab, mimeLabel, sortFilterDocs } from "./KnowledgeCorpus";
import * as api from "./api";

afterEach(() => vi.restoreAllMocks());

function doc(
  id: string,
  name: string,
  chunk_count: number,
  extra: Partial<api.DocumentInfo> = {},
): api.DocumentInfo {
  return {
    id,
    name,
    mime: "text/plain",
    size_bytes: 100,
    chunk_count,
    entity_count: 0,
    created_at: "2026-06-20T00:00:00Z",
    ...extra,
  };
}

const NO_STATS: api.EntityStats = { total: 0, by_type: {} };
function stats(total: number, by_type: api.EntityStats["by_type"]): api.EntityStats {
  return { total, by_type };
}

// The selected document is lifted into KnowledgePanel in the app; this stateful harness mirrors that
// so the corpus tests can drive the chunk inspector via the real row -> selection -> inspector path.
function CorpusHarness({ initialDocId = null }: { initialDocId?: string | null }): React.ReactElement {
  const [docId, setDocId] = useState<string | null>(initialDocId);
  return <KnowledgeCorpusTab token="demo" selectedDocId={docId} onSelectDocument={setDocId} />;
}

test("renders stat cards and a per-document table with an indexed flag", async () => {
  vi.spyOn(api, "fetchFiles").mockResolvedValue([
    doc("d1", "indexed.txt", 5, { entity_count: 4 }),
    doc("d2", "raw.txt", 0),
  ]);
  vi.spyOn(api, "fetchEntityStats").mockResolvedValue(stats(3, { person: 3 }));
  render(<CorpusHarness />);

  await waitFor(() => expect(screen.getByTestId("corpus-table")).toBeInTheDocument());

  // Stat cards: 2 documents, 5 total chunks, 3 entities (exact, from the stats endpoint).
  expect(screen.getByTestId("corpus-stat-documents")).toHaveTextContent("2");
  expect(screen.getByTestId("corpus-stat-chunks")).toHaveTextContent("5");
  expect(screen.getByTestId("corpus-stat-entities")).toHaveTextContent("3");
  // C-E: per-document entity count column (d1 sorts first: equal dates, name tie-break).
  expect(
    within(screen.getAllByTestId("corpus-row")[0]).getByTestId("corpus-col-entities"),
  ).toHaveTextContent("4");

  const rows = screen.getAllByTestId("corpus-row");
  expect(rows).toHaveLength(2);

  // The indexed doc reads "Indexed"; the zero-chunk doc is flagged amber "Not indexed".
  const indexed = within(rows[0]).getByTestId("corpus-status");
  expect(indexed).toHaveTextContent("Indexed");
  expect(indexed).toHaveAttribute("data-indexed", "true");

  const notIndexed = within(rows[1]).getByTestId("corpus-status");
  expect(notIndexed).toHaveTextContent("Not indexed");
  expect(notIndexed).toHaveAttribute("data-indexed", "false");
});

test("mimeLabel maps known types and falls back to extension then File", () => {
  expect(mimeLabel("application/pdf")).toBe("PDF");
  expect(mimeLabel("text/markdown")).toBe("Markdown");
  expect(mimeLabel("text/plain")).toBe("Text");
  expect(mimeLabel("image/png")).toBe("Image");
  expect(mimeLabel("", "report.PDF")).toBe("PDF"); // extension fallback, uppercased
  expect(mimeLabel(null, "noext")).toBe("File");
});

test("sortFilterDocs filters by name + status and sorts (tie-break always ascending)", () => {
  const files = [
    doc("a", "alpha.txt", 5, { size_bytes: 300 }),
    doc("b", "beta.txt", 0, { size_bytes: 100 }),
    doc("c", "carol.txt", 2, { size_bytes: 200 }),
  ];
  // Name search.
  expect(sortFilterDocs(files, { sort: "name", dir: "asc", q: "car", status: "all" })).toHaveLength(1);
  // Status filter: only unindexed (chunk_count 0).
  const un = sortFilterDocs(files, { sort: "name", dir: "asc", q: "", status: "unindexed" });
  expect(un.map((f) => f.id)).toEqual(["b"]);
  // Sort by size desc.
  const bySize = sortFilterDocs(files, { sort: "size", dir: "desc", q: "", status: "all" });
  expect(bySize.map((f) => f.id)).toEqual(["a", "c", "b"]);
});

test("table shows Type + Size columns and the corpus-size / unindexed stats", async () => {
  vi.spyOn(api, "fetchFiles").mockResolvedValue([
    doc("d1", "report.pdf", 5, { mime: "application/pdf", size_bytes: 1_200_000 }),
    doc("d2", "raw.txt", 0, { mime: "text/plain", size_bytes: 0 }),
  ]);
  vi.spyOn(api, "fetchEntityStats").mockResolvedValue(stats(1, { person: 1 }));
  render(<CorpusHarness />);

  await waitFor(() => expect(screen.getByTestId("corpus-table")).toBeInTheDocument());
  const types = screen.getAllByTestId("corpus-col-type").map((c) => c.textContent);
  expect(types).toContain("PDF");
  expect(types).toContain("Text");
  // Size cell: a null/zero size renders "—", not "0 B".
  expect(screen.getAllByTestId("corpus-col-size").some((c) => c.textContent === "—")).toBe(true);
  // C-C: a corpus-size card + an unindexed sub-line (one doc has 0 chunks).
  expect(screen.getByTestId("corpus-stat-size")).toBeInTheDocument();
  expect(screen.getByTestId("corpus-stat-unindexed")).toHaveTextContent("1 not indexed");
});

test("no unindexed sub-line when every document is indexed", async () => {
  vi.spyOn(api, "fetchFiles").mockResolvedValue([doc("d1", "a.txt", 3)]);
  vi.spyOn(api, "fetchEntityStats").mockResolvedValue(NO_STATS);
  render(<CorpusHarness />);

  await waitFor(() => expect(screen.getByTestId("corpus-table")).toBeInTheDocument());
  expect(screen.queryByTestId("corpus-stat-unindexed")).toBeNull();
});

test("search + status filter narrow the table, and corpus-no-match shows when nothing matches", async () => {
  vi.spyOn(api, "fetchFiles").mockResolvedValue([
    doc("d1", "alpha.txt", 5),
    doc("d2", "beta.txt", 0),
  ]);
  vi.spyOn(api, "fetchEntityStats").mockResolvedValue(NO_STATS);
  render(<CorpusHarness />);

  await waitFor(() => expect(screen.getByTestId("corpus-table")).toBeInTheDocument());
  // Search narrows to alpha.
  fireEvent.change(screen.getByTestId("corpus-search"), { target: { value: "alpha" } });
  expect(screen.getAllByTestId("corpus-row")).toHaveLength(1);
  // A non-matching search shows the distinct no-match message (not corpus-empty).
  fireEvent.change(screen.getByTestId("corpus-search"), { target: { value: "zzz" } });
  expect(screen.getByTestId("corpus-no-match")).toBeInTheDocument();
  expect(screen.queryByTestId("corpus-empty")).toBeNull();
  // Reset + filter to unindexed.
  fireEvent.change(screen.getByTestId("corpus-search"), { target: { value: "" } });
  fireEvent.click(screen.getByTestId("corpus-filter-unindexed"));
  const rows = screen.getAllByTestId("corpus-row");
  expect(rows).toHaveLength(1);
  expect(within(rows[0]).getByTestId("corpus-status")).toHaveTextContent("Not indexed");
});

test("the type breakdown lists each present type in TYPE_ORDER", async () => {
  vi.spyOn(api, "fetchFiles").mockResolvedValue([doc("d1", "a.txt", 1)]);
  vi.spyOn(api, "fetchEntityStats").mockResolvedValue(stats(3, { person: 2, org: 1 }));
  render(<CorpusHarness />);

  await waitFor(() => expect(screen.getByTestId("corpus-type-breakdown")).toBeInTheDocument());
  const types = screen.getAllByTestId("corpus-type-row").map((r) => r.getAttribute("data-type"));
  expect(types).toEqual(["person", "org"]); // present types only, in TYPE_ORDER
});

test("shows the empty state when there are no documents", async () => {
  vi.spyOn(api, "fetchFiles").mockResolvedValue([]);
  vi.spyOn(api, "fetchEntityStats").mockResolvedValue(NO_STATS);
  render(<CorpusHarness />);

  await waitFor(() => expect(screen.getByTestId("corpus-empty")).toBeInTheDocument());
  expect(screen.queryByTestId("corpus-table")).toBeNull();
});

test("surfaces a load error", async () => {
  vi.spyOn(api, "fetchFiles").mockRejectedValue(new Error("files request failed: 503"));
  vi.spyOn(api, "fetchEntityStats").mockResolvedValue(NO_STATS);
  render(<CorpusHarness />);

  await waitFor(() => expect(screen.getByTestId("corpus-error")).toBeInTheDocument());
});

test("clicking a document row opens the chunk inspector with its chunks", async () => {
  vi.spyOn(api, "fetchFiles").mockResolvedValue([doc("d1", "indexed.txt", 2)]);
  vi.spyOn(api, "fetchEntityStats").mockResolvedValue(NO_STATS);
  const chunkSpy = vi.spyOn(api, "fetchDocumentChunks").mockResolvedValue([
    { index: 0, text: "first chunk text" },
    { index: 1, text: "second chunk text" },
  ]);
  render(<CorpusHarness />);

  await waitFor(() => expect(screen.getByTestId("corpus-table")).toBeInTheDocument());
  // The row's name cell is a button (keyboard-reachable) carrying the doc id.
  const rowButton = screen.getByTestId("corpus-row-button");
  expect(rowButton).toHaveAttribute("data-doc-id", "d1");
  fireEvent.click(rowButton);

  const inspector = await screen.findByTestId("chunk-inspector");
  expect(chunkSpy).toHaveBeenCalledWith("demo", "d1");
  const rows = within(inspector).getAllByTestId("chunk-row");
  expect(rows).toHaveLength(2);
  expect(rows[0]).toHaveTextContent("first chunk text");
  expect(rows[1]).toHaveTextContent("second chunk text");
  expect(inspector).toHaveAttribute("aria-label", "Chunks for indexed.txt");
});

test("the chunk inspector shows an empty state and closes", async () => {
  vi.spyOn(api, "fetchFiles").mockResolvedValue([doc("d1", "indexed.txt", 0)]);
  vi.spyOn(api, "fetchEntityStats").mockResolvedValue(NO_STATS);
  vi.spyOn(api, "fetchDocumentChunks").mockResolvedValue([]);
  render(<CorpusHarness />);

  await waitFor(() => expect(screen.getByTestId("corpus-table")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("corpus-row-button"));

  expect(await screen.findByTestId("chunk-empty")).toBeInTheDocument();
  // Close clears the lifted selection -> the inspector unmounts.
  fireEvent.click(screen.getByTestId("chunk-inspector-close"));
  await waitFor(() => expect(screen.queryByTestId("chunk-inspector")).toBeNull());
});

test("the chunk inspector surfaces a load error", async () => {
  vi.spyOn(api, "fetchFiles").mockResolvedValue([doc("d1", "indexed.txt", 2)]);
  vi.spyOn(api, "fetchEntityStats").mockResolvedValue(NO_STATS);
  vi.spyOn(api, "fetchDocumentChunks").mockRejectedValue(new Error("document chunks request failed: 503"));
  render(<CorpusHarness />);

  await waitFor(() => expect(screen.getByTestId("corpus-table")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("corpus-row-button"));

  expect(await screen.findByTestId("chunk-error")).toBeInTheDocument();
});

test("a deep-linked document opens the inspector immediately (before the table loads)", async () => {
  vi.spyOn(api, "fetchFiles").mockResolvedValue([doc("d1", "indexed.txt", 1)]);
  vi.spyOn(api, "fetchEntityStats").mockResolvedValue(NO_STATS);
  vi.spyOn(api, "fetchDocumentChunks").mockResolvedValue([{ index: 0, text: "deep-linked chunk" }]);
  render(<CorpusHarness initialDocId="d1" />);

  const inspector = await screen.findByTestId("chunk-inspector");
  expect(within(inspector).getByTestId("chunk-row")).toHaveTextContent("deep-linked chunk");
});
