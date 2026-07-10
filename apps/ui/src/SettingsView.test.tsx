import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { SettingsView } from "./SettingsView";
import * as api from "./api";

// The Knowledge graph tab pulls in react-force-graph-2d; stub it so jsdom never touches a real canvas.
vi.mock("react-force-graph-2d", () => ({ default: () => <div data-testid="force-graph" /> }));

afterEach(() => vi.restoreAllMocks());

// The Documents default section, the Model stack / Knowledge panels, and the Knowledge graph picker
// all self-fetch when mounted; stub every source so no unhandled fetch escapes the test.
function stubFetches(): void {
  vi.spyOn(api, "fetchEntities").mockResolvedValue([]);
  vi.spyOn(api, "fetchFolders").mockResolvedValue([]);
  vi.spyOn(api, "fetchFiles").mockResolvedValue([]);
  // Security/ModelStack read egress + model fields off settings/defaults; give them safe shapes
  // (allowed_egress_hosts must be an array — the Security panel .join()s it on mount).
  vi.spyOn(api, "fetchSettings").mockResolvedValue({
    settings: { allowed_egress_hosts: null, egress_enabled: null } as unknown as api.TenantSettings,
    defaults: { allowed_egress_hosts: [], egress_enabled: false } as unknown as api.TenantSettingsDefaults,
  });
  vi.spyOn(api, "fetchProviders").mockResolvedValue({ default: "ollama", providers: [] });
  vi.spyOn(api, "fetchModels").mockResolvedValue({ defaultModel: "", models: [] });
}

function renderView(): void {
  render(
    <SettingsView token="demo" files={[]} uploading={false} onUpload={vi.fn()} onDelete={vi.fn()} />,
  );
}

test("the Knowledge nav item sits between Memory and Preferences", () => {
  stubFetches();
  renderView();

  const nav = screen.getByTestId("settings-nav");
  const ids = within(nav)
    .getAllByRole("tab")
    .map((b) => b.getAttribute("data-testid"));
  const memory = ids.indexOf("settings-nav-memory");
  const knowledge = ids.indexOf("settings-nav-knowledge");
  const preferences = ids.indexOf("settings-nav-preferences");

  expect(knowledge).toBe(memory + 1);
  expect(preferences).toBe(knowledge + 1);
  expect(screen.getByTestId("settings-nav-knowledge")).toHaveTextContent("Knowledge");
});

test("Security is the last nav item and Model stack is the first", () => {
  stubFetches();
  renderView();

  const ids = within(screen.getByTestId("settings-nav"))
    .getAllByRole("tab")
    .map((b) => b.getAttribute("data-testid"));
  expect(ids[0]).toBe("settings-nav-models");
  expect(ids[ids.length - 1]).toBe("settings-nav-security");
});

test("selecting Security shows the approvals + network egress cards", async () => {
  stubFetches();
  renderView();

  fireEvent.click(screen.getByTestId("settings-nav-security"));
  expect(await screen.findByTestId("security-approvals")).toBeInTheDocument();
  expect(screen.getByTestId("security-network")).toBeInTheDocument();
});

test("selecting Knowledge shows the panel with Graph + Corpus tabs", async () => {
  stubFetches();
  renderView();

  fireEvent.click(screen.getByTestId("settings-nav-knowledge"));

  expect(await screen.findByTestId("knowledge-panel")).toBeInTheDocument();
  expect(screen.getByTestId("knowledge-tab-graph")).toBeInTheDocument();
  expect(screen.getByTestId("knowledge-tab-corpus")).toBeInTheDocument();
});
