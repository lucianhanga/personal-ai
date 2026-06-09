import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { AppLogs } from "./AppLogs";
import * as api from "./api";

afterEach(() => vi.restoreAllMocks());

const LOGS = [
  {
    time: "2026-06-09T10:00:01Z",
    level: "WARNING",
    logger: "personalai_backend.app",
    message: "storage unavailable",
  },
  {
    time: "2026-06-09T10:00:00Z",
    level: "INFO",
    logger: "personalai_core.agent",
    message: "ran agent loop",
  },
];

test("lists recent log lines", async () => {
  vi.spyOn(api, "fetchLogs").mockResolvedValue(LOGS);
  render(<AppLogs token="demo" />);
  await waitFor(() => expect(screen.getAllByTestId("applogs-line")).toHaveLength(2));
  expect(screen.getByTestId("applogs-panel")).toHaveTextContent("storage unavailable");
  expect(screen.getByTestId("applogs-panel")).toHaveTextContent("WARNING");
});

test("shows empty state", async () => {
  vi.spyOn(api, "fetchLogs").mockResolvedValue([]);
  render(<AppLogs token="demo" />);
  await waitFor(() => expect(screen.getByTestId("applogs-empty")).toBeInTheDocument());
});

test("surfaces a load error", async () => {
  vi.spyOn(api, "fetchLogs").mockRejectedValue(new Error("logs request failed: 401"));
  render(<AppLogs token="demo" />);
  await waitFor(() => expect(screen.getByTestId("applogs-error")).toHaveTextContent(/401/));
});
