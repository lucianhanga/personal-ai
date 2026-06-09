import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { ToolLog } from "./ToolLog";
import * as api from "./api";

afterEach(() => vi.restoreAllMocks());

const ENTRIES = [
  {
    index: 1,
    type: "tool.denied",
    timestamp: "2026-06-09T10:00:01Z",
    tool: "http_fetch",
    ok: null,
    error: "approval required for high-risk tool",
    args: { url: "http://x" },
  },
  {
    index: 0,
    type: "tool.invoke",
    timestamp: "2026-06-09T10:00:00Z",
    tool: "calculator",
    ok: true,
    error: null,
    args: { expression: "2+2" },
  },
];

test("lists the current chat's tool calls", async () => {
  vi.spyOn(api, "fetchToolLog").mockResolvedValue(ENTRIES);
  render(<ToolLog token="demo" conversationId="c1" />);
  await waitFor(() => expect(screen.getAllByTestId("toollog-item")).toHaveLength(2));
  expect(screen.getByTestId("toollog-panel")).toHaveTextContent("Activity");
  expect(screen.getByTestId("toollog-panel")).toHaveTextContent("calculator");
  expect(screen.getByTestId("toollog-panel")).toHaveTextContent("http_fetch");
});

test("clicking an entry shows details", async () => {
  vi.spyOn(api, "fetchToolLog").mockResolvedValue(ENTRIES);
  render(<ToolLog token="demo" conversationId="c1" />);
  await waitFor(() => expect(screen.getByTestId("toollog-row-0")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("toollog-row-0"));
  await waitFor(() => expect(screen.getByTestId("toollog-detail")).toHaveTextContent("2+2"));
});

test("scopes the request to the selected conversation", async () => {
  const spy = vi.spyOn(api, "fetchToolLog").mockResolvedValue([]);
  render(<ToolLog token="demo" conversationId="conv-123" />);
  await waitFor(() => expect(spy).toHaveBeenCalledWith("demo", "conv-123"));
});

test("shows a hint and fetches nothing when no chat is selected", async () => {
  const spy = vi.spyOn(api, "fetchToolLog").mockResolvedValue(ENTRIES);
  render(<ToolLog token="demo" />);
  await waitFor(() => expect(screen.getByTestId("toollog-noconv")).toBeInTheDocument());
  expect(spy).not.toHaveBeenCalled();
});

test("shows empty state for a chat with no calls", async () => {
  vi.spyOn(api, "fetchToolLog").mockResolvedValue([]);
  render(<ToolLog token="demo" conversationId="c1" />);
  await waitFor(() => expect(screen.getByTestId("toollog-empty")).toBeInTheDocument());
});

test("surfaces a load error", async () => {
  vi.spyOn(api, "fetchToolLog").mockRejectedValue(new Error("tool log request failed: 401"));
  render(<ToolLog token="demo" conversationId="c1" />);
  await waitFor(() => expect(screen.getByTestId("toollog-error")).toHaveTextContent(/401/));
});
