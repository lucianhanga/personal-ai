import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { KnowledgePanel } from "./KnowledgePanel";
import * as api from "./api";

vi.mock("react-force-graph-2d", () => ({ default: () => <div data-testid="force-graph" /> }));

afterEach(() => vi.restoreAllMocks());

function entity(id: string, type: api.EntityType, name: string, mention_count = 1): api.Entity {
  return { id, type, name, mention_count };
}

function doc(id: string, name: string, chunk_count: number): api.DocumentInfo {
  return { id, name, mime: "text/plain", size_bytes: 100, chunk_count, created_at: "2026-06-20T00:00:00Z" };
}

test("opens on the Graph tab with the entity picker", async () => {
  vi.spyOn(api, "fetchEntities").mockResolvedValue([]);
  render(<KnowledgePanel token="demo" />);

  expect(screen.getByTestId("knowledge-panel-graph")).toBeInTheDocument();
  expect(screen.getByTestId("knowledge-graph-tab")).toBeInTheDocument();
  // The reused EntityBrowser is the picker AND the accessible alternative.
  expect(screen.getByTestId("entity-browser")).toBeInTheDocument();
  expect(screen.getByTestId("knowledge-tab-graph")).toHaveAttribute("aria-selected", "true");
});

test("switching to the Corpus tab renders the corpus overview", async () => {
  vi.spyOn(api, "fetchEntities").mockResolvedValue([]);
  vi.spyOn(api, "fetchFiles").mockResolvedValue([]);
  render(<KnowledgePanel token="demo" />);

  fireEvent.click(screen.getByTestId("knowledge-tab-corpus"));

  expect(screen.getByTestId("knowledge-panel-corpus")).toBeInTheDocument();
  expect(screen.getByTestId("knowledge-corpus-tab")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByTestId("corpus-empty")).toBeInTheDocument());
  expect(screen.getByTestId("knowledge-tab-corpus")).toHaveAttribute("aria-selected", "true");
});

test("Graph 'Open in Corpus' switches to the Corpus tab and opens that document's chunk inspector", async () => {
  const focus = entity("e1", "person", "Ada Lovelace", 7);
  vi.spyOn(api, "fetchEntities").mockResolvedValue([focus]);
  vi.spyOn(api, "fetchEntityNeighborhood").mockResolvedValue({
    focus,
    documents: [{ id: "d1", name: "notes.txt" }],
    neighbors: [],
  });
  vi.spyOn(api, "fetchDocumentEntities").mockResolvedValue([]);
  vi.spyOn(api, "fetchFiles").mockResolvedValue([doc("d1", "notes.txt", 3)]);
  const chunkSpy = vi
    .spyOn(api, "fetchDocumentChunks")
    .mockResolvedValue([{ index: 0, text: "ada chunk text" }]);

  render(<KnowledgePanel token="demo" />);

  // Focus the entity from the browser, then select its document in the rail.
  await waitFor(() =>
    expect(screen.getAllByTestId("entity-open-in-graph").length).toBeGreaterThan(0),
  );
  const openInGraph = screen
    .getAllByTestId("entity-open-in-graph")
    .find((b) => b.getAttribute("data-entity-id") === "e1")!;
  fireEvent.click(openInGraph);

  await screen.findByTestId("graph-detail");
  fireEvent.click(screen.getByTestId("graph-doc"));

  // The selected-document detail exposes the cross-tab deep link.
  const openInCorpus = await screen.findByTestId("graph-open-in-corpus");
  expect(openInCorpus).toHaveAttribute("data-doc-id", "d1");
  fireEvent.click(openInCorpus);

  // The panel switched to Corpus and opened the chunk inspector for d1.
  await waitFor(() =>
    expect(screen.getByTestId("knowledge-tab-corpus")).toHaveAttribute("aria-selected", "true"),
  );
  const inspector = await screen.findByTestId("chunk-inspector");
  expect(chunkSpy).toHaveBeenCalledWith("demo", "d1");
  expect(within(inspector).getByTestId("chunk-row")).toHaveTextContent("ada chunk text");
});
