import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { McpActivity } from "./McpActivity";
import * as api from "./api";

afterEach(() => vi.restoreAllMocks());

test("lists MCP tool-call activity", async () => {
  vi.spyOn(api, "fetchMcpLog").mockResolvedValue([
    {
      index: 1,
      type: "tool.allowed",
      timestamp: "2026-06-10T10:00:00Z",
      tool: "tavily.tavily_search",
      ok: true,
      error: null,
      args: { query: "x" },
    },
  ]);
  render(<McpActivity token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-activity-row")).toBeInTheDocument());
  expect(screen.getByTestId("mcp-activity")).toHaveTextContent("tavily.tavily_search");
});

test("shows the empty state", async () => {
  vi.spyOn(api, "fetchMcpLog").mockResolvedValue([]);
  render(<McpActivity token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-activity-empty")).toBeInTheDocument());
});

test("surfaces an error", async () => {
  vi.spyOn(api, "fetchMcpLog").mockRejectedValue(new Error("mcp log request failed: 401"));
  render(<McpActivity token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mcp-activity-error")).toHaveTextContent(/401/));
});
