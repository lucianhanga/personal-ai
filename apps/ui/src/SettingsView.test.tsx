import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { SettingsView } from "./SettingsView";
import * as api from "./api";

// The Knowledge graph tab pulls in react-force-graph-2d; stub it so jsdom never touches a real canvas.
vi.mock("react-force-graph-2d", () => ({ default: () => <div data-testid="force-graph" /> }));

afterEach(() => vi.restoreAllMocks());

// The default (Documents) section + the Knowledge graph picker both self-fetch on mount; settle them.
function stubFetches(): void {
  vi.spyOn(api, "fetchEntities").mockResolvedValue([]);
  vi.spyOn(api, "fetchFolders").mockResolvedValue([]);
  vi.spyOn(api, "fetchFiles").mockResolvedValue([]);
}

function renderView(): void {
  render(
    <SettingsView token="demo" files={[]} uploading={false} onUpload={vi.fn()} onDelete={vi.fn()} />,
  );
}

test("the Knowledge nav item sits between Memory and Network", () => {
  stubFetches();
  renderView();

  const nav = screen.getByTestId("settings-nav");
  const ids = within(nav)
    .getAllByRole("tab")
    .map((b) => b.getAttribute("data-testid"));
  const memory = ids.indexOf("settings-nav-memory");
  const knowledge = ids.indexOf("settings-nav-knowledge");
  const network = ids.indexOf("settings-nav-network");

  expect(knowledge).toBe(memory + 1);
  expect(network).toBe(knowledge + 1);
  expect(screen.getByTestId("settings-nav-knowledge")).toHaveTextContent("Knowledge");
});

test("selecting Knowledge shows the panel with Graph + Corpus tabs", async () => {
  stubFetches();
  renderView();

  fireEvent.click(screen.getByTestId("settings-nav-knowledge"));

  expect(await screen.findByTestId("knowledge-panel")).toBeInTheDocument();
  expect(screen.getByTestId("knowledge-tab-graph")).toBeInTheDocument();
  expect(screen.getByTestId("knowledge-tab-corpus")).toBeInTheDocument();
});
