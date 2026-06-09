import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { McpPanel } from "./McpPanel";
import * as api from "./api";

afterEach(() => vi.restoreAllMocks());

test("lists connected MCP servers and their tools", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([
    { name: "playwright", connected: true, tools: ["playwright.navigate", "playwright.click"], error: null },
  ]);
  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-server")).toBeInTheDocument());
  expect(screen.getByTestId("mcp-panel")).toHaveTextContent("playwright");
  expect(screen.getByTestId("mcp-panel")).toHaveTextContent("2 tools");
  expect(screen.getByTestId("mcp-panel")).toHaveTextContent("playwright.navigate");
});

test("shows a failed server with its error", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([
    { name: "bad", connected: false, tools: [], error: "no binary" },
  ]);
  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-server")).toHaveTextContent("no binary"));
});

test("shows the empty state when none configured", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([]);
  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-empty")).toBeInTheDocument());
});

test("surfaces a load error", async () => {
  vi.spyOn(api, "fetchMcp").mockRejectedValue(new Error("mcp request failed: 401"));
  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-error")).toHaveTextContent(/401/));
});
