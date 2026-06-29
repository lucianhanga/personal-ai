import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { KnowledgeGraphTab, pickLabeledNodeIds } from "./KnowledgeGraph";
import * as api from "./api";

// Capture what the (mocked) force-graph is handed, so we can assert the derived graph data without
// rendering a real canvas in jsdom. The accessible list/rail path is asserted via the real DOM.
const captured: { graphData?: { nodes?: unknown[]; links?: unknown[] } } = {};
vi.mock("react-force-graph-2d", () => ({
  default: (props: { graphData?: { nodes?: unknown[]; links?: unknown[] } }) => {
    captured.graphData = props.graphData;
    return (
      <div
        data-testid="force-graph"
        data-node-count={String(props.graphData?.nodes?.length ?? 0)}
        data-link-count={String(props.graphData?.links?.length ?? 0)}
      />
    );
  },
}));

afterEach(() => {
  vi.restoreAllMocks();
  captured.graphData = undefined;
});

function entity(id: string, type: api.EntityType, name: string, mention_count = 1): api.Entity {
  return { id, type, name, mention_count };
}

const FOCUS_ID = "e1";
const NEIGHBORHOOD: api.EntityNeighborhood = {
  focus: entity("e1", "person", "Ada Lovelace", 7),
  documents: [
    { id: "d1", name: "notes.txt" },
    { id: "d2", name: "paper.pdf" },
  ],
  neighbors: [{ entity: entity("e3", "org", "Acme Corp", 5), shared_documents: 2 }],
};

function openInGraph(id: string): void {
  const btn = screen
    .getAllByTestId("entity-open-in-graph")
    .find((b) => b.getAttribute("data-entity-id") === id)!;
  fireEvent.click(btn);
}

test("pickLabeledNodeIds: always the focus node plus the top-degree others", () => {
  const nodes = [
    { id: "f", label: "Focus", focus: true },
    { id: "a", label: "A" },
    { id: "b", label: "B" },
    { id: "c", label: "C" },
  ];
  // Degrees: a=2, b=1, c=0 (raw-id and node-object endpoints both supported).
  const links = [
    { source: "f", target: "a" },
    { source: "a", target: { id: "b" } },
  ];
  const ids = pickLabeledNodeIds(nodes, links, 1);
  expect(ids.has("f")).toBe(true); // focus always labeled
  expect(ids.has("a")).toBe(true); // highest degree among non-focus
  expect(ids.has("b")).toBe(false); // beyond n=1
  expect(ids.has("c")).toBe(false);
});

test("cold start lists top entities (and the legend) until one is focused", async () => {
  vi.spyOn(api, "fetchEntities").mockResolvedValue([NEIGHBORHOOD.focus]);
  render(<KnowledgeGraphTab token="demo" />);

  // G-D: with entities present and nothing focused, the launcher shows them as chips (not graph-empty).
  const launcher = await screen.findByTestId("graph-top-entities");
  expect(within(launcher).getByTestId("graph-top-entity")).toHaveTextContent("Ada Lovelace");
  expect(screen.queryByTestId("graph-empty")).not.toBeInTheDocument();
  // The legend (type key) + the new size/edge scale rows (G-C) are always visible.
  expect(screen.getByTestId("graph-legend")).toBeInTheDocument();
  expect(screen.getByTestId("graph-legend-size")).toBeInTheDocument();
  expect(screen.getByTestId("graph-legend-edge")).toBeInTheDocument();
});

test("cold start shows graph-empty only for a genuinely empty corpus", async () => {
  vi.spyOn(api, "fetchEntities").mockResolvedValue([]);
  render(<KnowledgeGraphTab token="demo" />);

  expect(await screen.findByTestId("graph-empty")).toBeInTheDocument();
  expect(screen.queryByTestId("graph-top-entities")).not.toBeInTheDocument();
});

test("clicking a top entity focuses the graph", async () => {
  vi.spyOn(api, "fetchEntities").mockResolvedValue([NEIGHBORHOOD.focus]);
  const nbSpy = vi.spyOn(api, "fetchEntityNeighborhood").mockResolvedValue(NEIGHBORHOOD);
  render(<KnowledgeGraphTab token="demo" />);

  fireEvent.click(await screen.findByTestId("graph-top-entity"));
  await screen.findByTestId("graph-detail");
  expect(nbSpy).toHaveBeenCalledWith("demo", "e1");
});

test("the camera controls are present and clickable once focused", async () => {
  vi.spyOn(api, "fetchEntities").mockResolvedValue([NEIGHBORHOOD.focus]);
  vi.spyOn(api, "fetchEntityNeighborhood").mockResolvedValue(NEIGHBORHOOD);
  render(<KnowledgeGraphTab token="demo" />);

  await waitFor(() =>
    expect(screen.getAllByTestId("entity-open-in-graph").length).toBeGreaterThan(0),
  );
  openInGraph(FOCUS_ID);
  await screen.findByTestId("graph-detail");
  fireEvent.click(screen.getByTestId("graph-zoom-fit"));
  fireEvent.click(screen.getByTestId("graph-zoom-reset"));
  expect(screen.getByTestId("graph-zoom-fit")).toBeEnabled();
});

test("shows a loading state while the neighborhood is fetched", async () => {
  vi.spyOn(api, "fetchEntities").mockResolvedValue([NEIGHBORHOOD.focus]);
  // A never-resolving promise keeps the graph in its loading state.
  vi.spyOn(api, "fetchEntityNeighborhood").mockReturnValue(new Promise(() => {}));
  render(<KnowledgeGraphTab token="demo" />);

  await waitFor(() =>
    expect(screen.getAllByTestId("entity-open-in-graph").length).toBeGreaterThan(0),
  );
  openInGraph(FOCUS_ID);

  expect(await screen.findByTestId("graph-loading")).toBeInTheDocument();
});

test("focusing an entity renders the graph data + the accessible detail rail", async () => {
  vi.spyOn(api, "fetchEntities").mockResolvedValue([NEIGHBORHOOD.focus]);
  vi.spyOn(api, "fetchEntityNeighborhood").mockResolvedValue(NEIGHBORHOOD);
  render(<KnowledgeGraphTab token="demo" />);

  await waitFor(() =>
    expect(screen.getAllByTestId("entity-open-in-graph").length).toBeGreaterThan(0),
  );
  openInGraph(FOCUS_ID);

  // The detail rail (accessible alternative) names the focus + its docs + co-occurring entities.
  const detail = await screen.findByTestId("graph-detail");
  expect(within(detail).getByTestId("graph-focus")).toHaveTextContent("Ada Lovelace");
  expect(within(detail).getAllByTestId("graph-doc")).toHaveLength(2);
  expect(within(detail).getAllByTestId("graph-neighbor")).toHaveLength(1);
  expect(within(detail).getByTestId("graph-neighbor")).toHaveTextContent("2 shared");

  // The canvas (aria-hidden) received focus + 2 docs + 1 neighbor = 4 nodes, 3 edges.
  const canvas = screen.getByTestId("graph-canvas");
  expect(canvas).toHaveAttribute("aria-hidden", "true");
  expect(screen.getByTestId("force-graph")).toHaveAttribute("data-node-count", "4");
  expect(screen.getByTestId("force-graph")).toHaveAttribute("data-link-count", "3");
  expect(api.fetchEntityNeighborhood).toHaveBeenCalledWith("demo", "e1");
});

test("selecting a document drives the rail to that document's entities", async () => {
  vi.spyOn(api, "fetchEntities").mockResolvedValue([NEIGHBORHOOD.focus]);
  vi.spyOn(api, "fetchEntityNeighborhood").mockResolvedValue(NEIGHBORHOOD);
  const docSpy = vi
    .spyOn(api, "fetchDocumentEntities")
    .mockResolvedValue([entity("e9", "location", "Berlin", 2)]);
  render(<KnowledgeGraphTab token="demo" />);

  await waitFor(() =>
    expect(screen.getAllByTestId("entity-open-in-graph").length).toBeGreaterThan(0),
  );
  openInGraph(FOCUS_ID);
  await screen.findByTestId("graph-detail");

  const firstDoc = screen.getAllByTestId("graph-doc")[0];
  fireEvent.click(firstDoc);

  const docDetail = await screen.findByTestId("graph-doc-detail");
  expect(within(docDetail).getByTestId("graph-doc-entity")).toHaveTextContent("Berlin");
  expect(docSpy).toHaveBeenCalledWith("demo", "d1");
});

test("clicking a co-occurring entity re-focuses the graph", async () => {
  vi.spyOn(api, "fetchEntities").mockResolvedValue([NEIGHBORHOOD.focus]);
  const nbSpy = vi.spyOn(api, "fetchEntityNeighborhood").mockResolvedValue(NEIGHBORHOOD);
  render(<KnowledgeGraphTab token="demo" />);

  await waitFor(() =>
    expect(screen.getAllByTestId("entity-open-in-graph").length).toBeGreaterThan(0),
  );
  openInGraph(FOCUS_ID);
  await screen.findByTestId("graph-detail");

  fireEvent.click(screen.getByTestId("graph-neighbor"));
  await waitFor(() => expect(nbSpy).toHaveBeenLastCalledWith("demo", "e3"));
});

test("the co-occurrence toggle collapses the document nodes to a direct focus->entity projection", async () => {
  vi.spyOn(api, "fetchEntities").mockResolvedValue([NEIGHBORHOOD.focus]);
  vi.spyOn(api, "fetchEntityNeighborhood").mockResolvedValue(NEIGHBORHOOD);
  render(<KnowledgeGraphTab token="demo" />);

  await waitFor(() =>
    expect(screen.getAllByTestId("entity-open-in-graph").length).toBeGreaterThan(0),
  );
  openInGraph(FOCUS_ID);
  await screen.findByTestId("graph-detail");

  // Bipartite (default): focus + 2 docs + 1 neighbor = 4 nodes, 3 edges. A document node is present.
  expect(screen.getByTestId("graph-layout-bipartite")).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("force-graph")).toHaveAttribute("data-node-count", "4");
  const bipartiteNodes = captured.graphData?.nodes as { kind?: string }[];
  expect(bipartiteNodes.some((n) => n.kind === "document")).toBe(true);

  // Switch to Co-occurrence: documents hidden -> focus + 1 neighbor = 2 nodes, 1 weighted edge.
  fireEvent.click(screen.getByTestId("graph-layout-cooccurrence"));

  await waitFor(() =>
    expect(screen.getByTestId("force-graph")).toHaveAttribute("data-node-count", "2"),
  );
  expect(screen.getByTestId("force-graph")).toHaveAttribute("data-link-count", "1");
  expect(screen.getByTestId("graph-layout-cooccurrence")).toHaveAttribute("aria-pressed", "true");

  const nodes = captured.graphData?.nodes as { kind?: string }[];
  expect(nodes.some((n) => n.kind === "document")).toBe(false);
  // The only edge is focus -> neighbor, carrying the co-occurrence weight (shared_documents).
  const links = captured.graphData?.links as { source?: string; target?: string; weight?: number }[];
  expect(links).toHaveLength(1);
  expect(links[0]).toMatchObject({ source: "e1", target: "e3", weight: 2 });

  // The accessible detail rail still lists both documents in either projection.
  expect(screen.getAllByTestId("graph-doc")).toHaveLength(2);
});

test("surfaces a graph load error", async () => {
  vi.spyOn(api, "fetchEntities").mockResolvedValue([NEIGHBORHOOD.focus]);
  vi.spyOn(api, "fetchEntityNeighborhood").mockRejectedValue(new Error("neighborhood request failed: 503"));
  render(<KnowledgeGraphTab token="demo" />);

  await waitFor(() =>
    expect(screen.getAllByTestId("entity-open-in-graph").length).toBeGreaterThan(0),
  );
  openInGraph(FOCUS_ID);

  expect(await screen.findByTestId("graph-error")).toBeInTheDocument();
});
