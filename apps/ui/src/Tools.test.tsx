import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { Tools } from "./Tools";
import * as api from "./api";

afterEach(() => vi.restoreAllMocks());

const TOOLS = [
  {
    name: "calculator",
    version: "1.0.0",
    risk: "low",
    capabilities: ["arithmetic"],
    permissions: [],
    inputs: {},
    outputs: {},
  },
  {
    name: "http_fetch",
    version: "1.0.0",
    risk: "high",
    capabilities: ["http.get"],
    permissions: [{ type: "network", scope: "*" }],
    inputs: {},
    outputs: {},
  },
];

test("lists tools with risk + permissions", async () => {
  vi.spyOn(api, "fetchTools").mockResolvedValue(TOOLS);
  render(<Tools token="demo" />);
  await waitFor(() => expect(screen.getByTestId("tool-list")).toHaveTextContent("calculator"));
  expect(screen.getByTestId("tool-list")).toHaveTextContent("http_fetch");
  expect(screen.getByTestId("tool-list")).toHaveTextContent("network");
});

test("runs a tool and shows the result", async () => {
  vi.spyOn(api, "fetchTools").mockResolvedValue(TOOLS);
  const invoke = vi.spyOn(api, "invokeTool").mockResolvedValue({ ok: true, data: { result: 14 } });
  render(<Tools token="demo" />);
  await waitFor(() => expect(screen.getByTestId("tool-select")).toBeInTheDocument());

  fireEvent.change(screen.getByTestId("tool-args"), { target: { value: '{"expression":"2+3*4"}' } });
  fireEvent.click(screen.getByTestId("tool-run"));

  await waitFor(() => expect(invoke).toHaveBeenCalled());
  await waitFor(() => expect(screen.getByTestId("tool-result")).toHaveTextContent("14"));
});

test("shows a tool error result", async () => {
  vi.spyOn(api, "fetchTools").mockResolvedValue(TOOLS);
  vi.spyOn(api, "invokeTool").mockResolvedValue({ ok: false, error: "egress not allowed" });
  render(<Tools token="demo" />);
  await waitFor(() => expect(screen.getByTestId("tool-run")).toBeEnabled());
  fireEvent.click(screen.getByTestId("tool-run"));
  await waitFor(() =>
    expect(screen.getByTestId("tool-result")).toHaveTextContent("egress not allowed"),
  );
});

test("surfaces a load error", async () => {
  vi.spyOn(api, "fetchTools").mockRejectedValue(new Error("tools request failed: 401"));
  render(<Tools token="demo" />);
  await waitFor(() => expect(screen.getByTestId("tools-error")).toHaveTextContent(/401/));
});
