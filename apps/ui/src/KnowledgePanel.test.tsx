import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { KnowledgePanel } from "./KnowledgePanel";
import * as api from "./api";

vi.mock("react-force-graph-2d", () => ({ default: () => <div data-testid="force-graph" /> }));

afterEach(() => vi.restoreAllMocks());

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
