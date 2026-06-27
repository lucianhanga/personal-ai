import { render, screen, waitFor, within } from "@testing-library/react";
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

test("renders stat cards and a per-document table with an indexed flag", async () => {
  vi.spyOn(api, "fetchFiles").mockResolvedValue([doc("d1", "indexed.txt", 5), doc("d2", "raw.txt", 0)]);
  vi.spyOn(api, "fetchEntities").mockResolvedValue([entity("a"), entity("b"), entity("c")]);
  render(<KnowledgeCorpusTab token="demo" />);

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
  render(<KnowledgeCorpusTab token="demo" />);

  await waitFor(() => expect(screen.getByTestId("corpus-empty")).toBeInTheDocument());
  expect(screen.queryByTestId("corpus-table")).toBeNull();
});

test("surfaces a load error", async () => {
  vi.spyOn(api, "fetchFiles").mockRejectedValue(new Error("files request failed: 503"));
  vi.spyOn(api, "fetchEntities").mockResolvedValue([]);
  render(<KnowledgeCorpusTab token="demo" />);

  await waitFor(() => expect(screen.getByTestId("corpus-error")).toBeInTheDocument());
});
