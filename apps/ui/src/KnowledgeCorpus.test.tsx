import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, test, vi } from "vitest";

import { KnowledgeCorpusTab } from "./KnowledgeCorpus";
import * as api from "./api";

afterEach(() => vi.restoreAllMocks());

function doc(id: string, name: string, chunk_count: number): api.DocumentInfo {
  return { id, name, mime: "text/plain", size_bytes: 100, chunk_count, created_at: "2026-06-20T00:00:00Z" };
}

function entity(id: string): api.Entity {
  return { id, type: "person", name: id, mention_count: 1 };
}

// The selected document is lifted into KnowledgePanel in the app; this stateful harness mirrors that
// so the corpus tests can drive the chunk inspector via the real row -> selection -> inspector path.
function CorpusHarness({ initialDocId = null }: { initialDocId?: string | null }): React.ReactElement {
  const [docId, setDocId] = useState<string | null>(initialDocId);
  return <KnowledgeCorpusTab token="demo" selectedDocId={docId} onSelectDocument={setDocId} />;
}

test("renders stat cards and a per-document table with an indexed flag", async () => {
  vi.spyOn(api, "fetchFiles").mockResolvedValue([doc("d1", "indexed.txt", 5), doc("d2", "raw.txt", 0)]);
  vi.spyOn(api, "fetchEntities").mockResolvedValue([entity("a"), entity("b"), entity("c")]);
  render(<CorpusHarness />);

  await waitFor(() => expect(screen.getByTestId("corpus-table")).toBeInTheDocument());

  // Stat cards: 2 documents, 5 total chunks, 3 entities.
  expect(screen.getByTestId("corpus-stat-documents")).toHaveTextContent("2");
  expect(screen.getByTestId("corpus-stat-chunks")).toHaveTextContent("5");
  expect(screen.getByTestId("corpus-stat-entities")).toHaveTextContent("3");

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

test("shows the empty state when there are no documents", async () => {
  vi.spyOn(api, "fetchFiles").mockResolvedValue([]);
  vi.spyOn(api, "fetchEntities").mockResolvedValue([]);
  render(<CorpusHarness />);

  await waitFor(() => expect(screen.getByTestId("corpus-empty")).toBeInTheDocument());
  expect(screen.queryByTestId("corpus-table")).toBeNull();
});

test("surfaces a load error", async () => {
  vi.spyOn(api, "fetchFiles").mockRejectedValue(new Error("files request failed: 503"));
  vi.spyOn(api, "fetchEntities").mockResolvedValue([]);
  render(<CorpusHarness />);

  await waitFor(() => expect(screen.getByTestId("corpus-error")).toBeInTheDocument());
});

test("clicking a document row opens the chunk inspector with its chunks", async () => {
  vi.spyOn(api, "fetchFiles").mockResolvedValue([doc("d1", "indexed.txt", 2)]);
  vi.spyOn(api, "fetchEntities").mockResolvedValue([]);
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
  vi.spyOn(api, "fetchEntities").mockResolvedValue([]);
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
  vi.spyOn(api, "fetchEntities").mockResolvedValue([]);
  vi.spyOn(api, "fetchDocumentChunks").mockRejectedValue(new Error("document chunks request failed: 503"));
  render(<CorpusHarness />);

  await waitFor(() => expect(screen.getByTestId("corpus-table")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("corpus-row-button"));

  expect(await screen.findByTestId("chunk-error")).toBeInTheDocument();
});

test("a deep-linked document opens the inspector immediately (before the table loads)", async () => {
  vi.spyOn(api, "fetchFiles").mockResolvedValue([doc("d1", "indexed.txt", 1)]);
  vi.spyOn(api, "fetchEntities").mockResolvedValue([]);
  vi.spyOn(api, "fetchDocumentChunks").mockResolvedValue([{ index: 0, text: "deep-linked chunk" }]);
  render(<CorpusHarness initialDocId="d1" />);

  const inspector = await screen.findByTestId("chunk-inspector");
  expect(within(inspector).getByTestId("chunk-row")).toHaveTextContent("deep-linked chunk");
});
