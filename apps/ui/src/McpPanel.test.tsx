import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { McpPanel } from "./McpPanel";
import * as api from "./api";
import type { McpHealth, McpServer } from "./api";

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

const HEALTHY: McpHealth = {
  name: "playwright",
  status: "healthy",
  latency_ms: 42,
  tool_count: 23,
  error: null,
  checked_at: "now",
};

test("lists servers with status and tools", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([srv()]);
  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-server")).toBeInTheDocument());
  expect(screen.getByTestId("mcp-manager")).toHaveTextContent("playwright");
  expect(screen.getByTestId("mcp-manager")).toHaveTextContent("2 tools");
});

test("Test button checks health and shows a badge", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([srv()]);
  const h = vi.spyOn(api, "checkMcpHealth").mockResolvedValue(HEALTHY);
  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-test")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("mcp-test"));
  await waitFor(() => expect(screen.getByTestId("mcp-health")).toHaveTextContent("healthy"));
  expect(h).toHaveBeenCalledWith("demo", "playwright");
});

test("adds a server via the form", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([]);
  const up = vi.spyOn(api, "upsertMcpServer").mockResolvedValue(srv());
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-empty")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("mcp-add"));
  fireEvent.change(screen.getByTestId("mcp-form-name"), { target: { value: "time" } });
  fireEvent.change(screen.getByTestId("mcp-form-command"), { target: { value: "uvx" } });
  fireEvent.change(screen.getByTestId("mcp-form-args"), { target: { value: "mcp-server-time" } });
  fireEvent.click(screen.getByTestId("mcp-form-save"));
  await waitFor(() =>
    expect(up).toHaveBeenCalledWith("demo", "time", {
      command: "uvx",
      args: ["mcp-server-time"],
      env: {},
      enabled: true,
    }),
  );
});

test("switches the editor from Form to JSON carrying the data", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([]);
  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-empty")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("mcp-add"));
  fireEvent.change(screen.getByTestId("mcp-form-command"), { target: { value: "npx" } });
  fireEvent.click(screen.getByTestId("mcp-tab-json"));
  expect((screen.getByTestId("mcp-json-text") as HTMLTextAreaElement).value).toContain("npx");
});

test("saving the JSON tab parses and upserts", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([]);
  const up = vi.spyOn(api, "upsertMcpServer").mockResolvedValue(srv());
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-empty")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("mcp-add"));
  fireEvent.change(screen.getByTestId("mcp-form-name"), { target: { value: "git" } });
  fireEvent.click(screen.getByTestId("mcp-tab-json"));
  fireEvent.change(screen.getByTestId("mcp-json-text"), {
    target: { value: '{"command":"uvx","args":["mcp-server-git"],"env":{},"enabled":true}' },
  });
  fireEvent.click(screen.getByTestId("mcp-form-save"));
  await waitFor(() =>
    expect(up).toHaveBeenCalledWith("demo", "git", {
      command: "uvx",
      args: ["mcp-server-git"],
      env: {},
      enabled: true,
    }),
  );
});

test("whole-config: open, edit, apply", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([srv()]);
  vi.spyOn(api, "fetchMcpConfig").mockResolvedValue({
    playwright: { command: "npx", args: [], env: {}, enabled: true },
  });
  const put = vi.spyOn(api, "putMcpConfig").mockResolvedValue([]);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-server")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("mcp-edit-all"));
  await waitFor(() => expect(screen.getByTestId("mcp-config-text")).toBeInTheDocument());
  fireEvent.change(screen.getByTestId("mcp-config-text"), {
    target: { value: '{"mcpServers":{"time":{"command":"uvx","args":["mcp-server-time"]}}}' },
  });
  fireEvent.click(screen.getByTestId("mcp-config-apply"));
  await waitFor(() =>
    expect(put).toHaveBeenCalledWith("demo", {
      time: { command: "uvx", args: ["mcp-server-time"] },
    }),
  );
});

test("export copies the config to the clipboard", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([srv()]);
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-export-all")).toBeEnabled());
  fireEvent.click(screen.getByTestId("mcp-export-all"));
  expect(writeText).toHaveBeenCalledWith(expect.stringContaining("playwright"));
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

test("import parses pasted JSON and calls the API", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([]);
  const imp = vi.spyOn(api, "importMcpServers").mockResolvedValue([srv()]);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-empty")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("mcp-import-open"));
  fireEvent.change(screen.getByTestId("mcp-import-text"), {
    target: { value: '{"mcpServers":{"time":{"command":"uvx","args":["mcp-server-time"]}}}' },
  });
  fireEvent.click(screen.getByTestId("mcp-import-run"));
  await waitFor(() =>
    expect(imp).toHaveBeenCalledWith("demo", { time: { command: "uvx", args: ["mcp-server-time"] } }),
  );
});

test("invalid JSON in the editor surfaces an error", async () => {
  vi.spyOn(api, "fetchMcp").mockResolvedValue([]);
  render(<McpPanel token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-empty")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("mcp-add"));
  fireEvent.change(screen.getByTestId("mcp-form-name"), { target: { value: "x" } });
  fireEvent.click(screen.getByTestId("mcp-tab-json"));
  fireEvent.change(screen.getByTestId("mcp-json-text"), { target: { value: "not json" } });
  fireEvent.click(screen.getByTestId("mcp-form-save"));
  await waitFor(() => expect(screen.getByTestId("mcp-error")).toHaveTextContent(/invalid JSON/));
});
