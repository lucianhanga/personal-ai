import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { McpPanel } from "./McpPanel";
import * as api from "./api";
import type { McpServer } from "./api";

afterEach(() => vi.restoreAllMocks());

function srv(over: Partial<McpServer> = {}): McpServer {
  return {
    name: "playwright",
    command: "npx",
    args: ["-y", "@playwright/mcp@latest"],
    env: {},
    enabled: true,
    connected: true,
    tools: ["playwright.navigate", "playwright.click"],
    error: null,
    ...over,
  };
}

test("lists servers with status and tools", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([srv()]);
  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-server")).toBeInTheDocument());
  expect(screen.getByTestId("mcp-panel")).toHaveTextContent("playwright");
  expect(screen.getByTestId("mcp-panel")).toHaveTextContent("2 tools");
});

test("shows a failed server with its error", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([
    srv({ connected: false, tools: [], error: "no binary" }),
  ]);
  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-server")).toHaveTextContent("no binary"));
});

test("empty state when none configured", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([]);
  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-empty")).toBeInTheDocument());
});

test("adds a server via the form (upsert called, env parsed)", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([]);
  const up = vi.spyOn(api, "upsertMcpServer").mockResolvedValue(srv());
  vi.spyOn(window, "confirm").mockReturnValue(true);

  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-empty")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("mcp-add"));
  fireEvent.change(screen.getByTestId("mcp-form-name"), { target: { value: "tavily" } });
  fireEvent.change(screen.getByTestId("mcp-form-command"), { target: { value: "npx" } });
  fireEvent.change(screen.getByTestId("mcp-form-args"), {
    target: { value: "-y tavily-mcp@latest" },
  });
  fireEvent.change(screen.getByTestId("mcp-form-env"), {
    target: { value: "TAVILY_API_KEY=abc\n# comment\n" },
  });
  fireEvent.click(screen.getByTestId("mcp-form-save"));

  await waitFor(() =>
    expect(up).toHaveBeenCalledWith("demo", "tavily", {
      command: "npx",
      args: ["-y", "tavily-mcp@latest"],
      env: { TAVILY_API_KEY: "abc" },
      enabled: true,
    }),
  );
});

test("toggle disconnect calls upsert with enabled=false", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([srv()]);
  const up = vi.spyOn(api, "upsertMcpServer").mockResolvedValue(srv({ enabled: false }));

  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-toggle")).toHaveTextContent("Disconnect"));
  fireEvent.click(screen.getByTestId("mcp-toggle"));
  await waitFor(() =>
    expect(up).toHaveBeenCalledWith(
      "demo",
      "playwright",
      expect.objectContaining({ enabled: false }),
    ),
  );
});

test("import parses pasted JSON and calls the API", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([]);
  const imp = vi.spyOn(api, "importMcpServers").mockResolvedValue([srv()]);
  vi.spyOn(window, "confirm").mockReturnValue(true);

  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-empty")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("mcp-import-open"));
  fireEvent.change(screen.getByTestId("mcp-import-text"), {
    target: {
      value: '{"mcpServers":{"time":{"command":"uvx","args":["mcp-server-time"]}}}',
    },
  });
  fireEvent.click(screen.getByTestId("mcp-import-run"));

  await waitFor(() =>
    expect(imp).toHaveBeenCalledWith("demo", {
      time: { command: "uvx", args: ["mcp-server-time"] },
    }),
  );
});

test("import shows an error on invalid JSON", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([]);
  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-empty")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("mcp-import-open"));
  fireEvent.change(screen.getByTestId("mcp-import-text"), { target: { value: "not json" } });
  fireEvent.click(screen.getByTestId("mcp-import-run"));
  await waitFor(() => expect(screen.getByTestId("mcp-error")).toHaveTextContent(/invalid JSON/));
});

test("delete asks for confirmation and calls the API", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([srv()]);
  const del = vi.spyOn(api, "deleteMcpServer").mockResolvedValue();
  vi.spyOn(window, "confirm").mockReturnValue(true);

  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-delete")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("mcp-delete"));
  await waitFor(() => expect(del).toHaveBeenCalledWith("demo", "playwright"));
});
