import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { EntityBrowser } from "./EntityBrowser";
import * as api from "./api";

afterEach(() => vi.restoreAllMocks());

function entity(id: string, type: api.EntityType, name: string, mention_count = 1): api.Entity {
  return { id, type, name, mention_count };
}

const CORPUS: api.Entity[] = [
  entity("e1", "person", "Ada Lovelace", 7),
  entity("e2", "person", "Alan Turing", 3),
  entity("e3", "org", "Acme Corp", 5),
  entity("e4", "location", "Berlin", 2),
];

test("lists entities grouped by type, each with its mention count", async () => {
  vi.spyOn(api, "fetchEntities").mockResolvedValue(CORPUS);
  render(<EntityBrowser token="demo" />);

  await waitFor(() => expect(screen.getByTestId("entity-groups")).toBeInTheDocument());
  // Each type forms its own group.
  expect(screen.getByTestId("entity-group-person")).toBeInTheDocument();
  expect(screen.getByTestId("entity-group-org")).toBeInTheDocument();
  expect(screen.getByTestId("entity-group-location")).toBeInTheDocument();
  // A chip shows the name + mention count.
  const ada = screen.getByText("Ada Lovelace").closest("button")!;
  expect(ada).toHaveTextContent("7 mentions");
});

test("the type filter re-queries the entities API by type", async () => {
  const spy = vi.spyOn(api, "fetchEntities").mockImplementation(async (_t, opts) =>
    opts?.type === "org" ? [entity("e3", "org", "Acme Corp", 5)] : CORPUS,
  );
  render(<EntityBrowser token="demo" />);
  await waitFor(() => expect(screen.getByText("Ada Lovelace")).toBeInTheDocument());

  fireEvent.click(screen.getByTestId("entity-filter-org"));
  await waitFor(() => expect(screen.queryByText("Ada Lovelace")).toBeNull());
  expect(screen.getByText("Acme Corp")).toBeInTheDocument();
  expect(spy).toHaveBeenLastCalledWith("demo", expect.objectContaining({ type: "org" }));
});

test("the debounced name search re-queries with q", async () => {
  const spy = vi.spyOn(api, "fetchEntities").mockImplementation(async (_t, opts) =>
    opts?.q ? [entity("e1", "person", "Ada Lovelace", 7)] : CORPUS,
  );
  render(<EntityBrowser token="demo" />);
  await waitFor(() => expect(screen.getByText("Alan Turing")).toBeInTheDocument());

  fireEvent.change(screen.getByTestId("entity-search"), { target: { value: "ada" } });
  // Debounced (~250ms) -> re-query with q, Alan drops out.
  await waitFor(() => expect(screen.queryByText("Alan Turing")).toBeNull());
  expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
  expect(spy).toHaveBeenLastCalledWith("demo", expect.objectContaining({ q: "ada" }));
});

test("clicking an entity opens its detail: documents + edges", async () => {
  vi.spyOn(api, "fetchEntities").mockResolvedValue(CORPUS);
  vi.spyOn(api, "fetchEntityDetail").mockResolvedValue({
    entity: CORPUS[0],
    documents: ["doc-1", "doc-2"],
    edges: [{ relation: "works_at", dst_entity_id: "e3" }],
  });
  render(<EntityBrowser token="demo" />);
  await waitFor(() => expect(screen.getByText("Ada Lovelace")).toBeInTheDocument());

  fireEvent.click(screen.getByText("Ada Lovelace"));
  await waitFor(() => expect(screen.getByTestId("entity-detail")).toBeInTheDocument());
  const detail = screen.getByTestId("entity-detail");
  // The source documents render as copy-id affordances.
  expect(within(detail).getAllByTestId("entity-document")).toHaveLength(2);
  expect(within(detail).getByText("doc-1")).toBeInTheDocument();
  // The edge renders as "relation -> other entity".
  const edge = within(detail).getByTestId("entity-edge");
  expect(edge).toHaveTextContent("works_at");
  expect(edge).toHaveTextContent("e3");
  expect(api.fetchEntityDetail).toHaveBeenCalledWith("demo", "e1");
});

test("re-clicking the open entity collapses its detail", async () => {
  vi.spyOn(api, "fetchEntities").mockResolvedValue(CORPUS);
  vi.spyOn(api, "fetchEntityDetail").mockResolvedValue({
    entity: CORPUS[0],
    documents: ["doc-1"],
    edges: [],
  });
  render(<EntityBrowser token="demo" />);
  await waitFor(() => expect(screen.getByText("Ada Lovelace")).toBeInTheDocument());

  fireEvent.click(screen.getByText("Ada Lovelace"));
  await waitFor(() => expect(screen.getByTestId("entity-detail")).toBeInTheDocument());
  fireEvent.click(screen.getByText("Ada Lovelace"));
  expect(screen.queryByTestId("entity-detail")).toBeNull();
});

test("an edge target navigates to that entity's detail", async () => {
  vi.spyOn(api, "fetchEntities").mockResolvedValue(CORPUS);
  const detailSpy = vi
    .spyOn(api, "fetchEntityDetail")
    .mockResolvedValueOnce({
      entity: CORPUS[0],
      documents: [],
      edges: [{ relation: "works_at", dst_entity_id: "e3" }],
    })
    .mockResolvedValueOnce({ entity: CORPUS[2], documents: ["doc-9"], edges: [] });
  render(<EntityBrowser token="demo" />);
  await waitFor(() => expect(screen.getByText("Ada Lovelace")).toBeInTheDocument());

  fireEvent.click(screen.getByText("Ada Lovelace"));
  await waitFor(() => expect(screen.getByTestId("entity-edge-target")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("entity-edge-target"));
  await waitFor(() => expect(detailSpy).toHaveBeenLastCalledWith("demo", "e3"));
});

test("shows the corpus-empty message when there are no entities", async () => {
  vi.spyOn(api, "fetchEntities").mockResolvedValue([]);
  render(<EntityBrowser token="demo" />);
  await waitFor(() => expect(screen.getByTestId("entities-empty")).toBeInTheDocument());
  expect(screen.getByTestId("entities-empty")).toHaveTextContent(/extracted as documents are indexed/i);
});

test("shows a 'no match' message when a filter yields nothing", async () => {
  vi.spyOn(api, "fetchEntities").mockImplementation(async (_t, opts) =>
    opts?.type ? [] : CORPUS,
  );
  render(<EntityBrowser token="demo" />);
  await waitFor(() => expect(screen.getByText("Ada Lovelace")).toBeInTheDocument());

  fireEvent.click(screen.getByTestId("entity-filter-event"));
  await waitFor(() => expect(screen.getByTestId("entities-empty")).toHaveTextContent(/no entities match/i));
});

test("surfaces a load error", async () => {
  vi.spyOn(api, "fetchEntities").mockRejectedValue(new Error("entities request failed: 503"));
  render(<EntityBrowser token="demo" />);
  await waitFor(() => expect(screen.getByTestId("entity-error")).toBeInTheDocument());
});
