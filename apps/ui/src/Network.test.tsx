import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { Network } from "./Network";
import * as api from "./api";
import type { TenantSettings } from "./api";

afterEach(() => vi.restoreAllMocks());

const SETTINGS: TenantSettings = {
  model_provider: null,
  default_model: null,
  ollama_host: null,
  ollama_num_ctx: null,
  ollama_keep_alive: null,
  embed_provider: null,
  embed_model: null,
  openai_base_url: null,
  agent_mode: null,
  agent_graph_enabled: null,
  agent_human_gate: null,
  agent_accuracy_mode: null,
  agent_max_iterations: null,
  agent_timeout_seconds: null,
  memory_enabled: null,
  grounding_enabled: null,
  max_upload_bytes: null,
  egress_enabled: null,
  allowed_egress_hosts: null,
  transcribe_provider: null,
  transcribe_enabled: null,
  transcribe_base_url: null,
  transcribe_model: null,
  transcribe_language: null,
};

function mockLoad(settings: Partial<TenantSettings> = {}): void {
  vi.spyOn(api, "fetchSettings").mockResolvedValue({
    settings: { ...SETTINGS, ...settings },
    defaults: { egress_enabled: false, allowed_egress_hosts: [] } as never,
  });
}

test("defaults to off and shows the blocked (deny all) state in red", async () => {
  mockLoad();
  render(<Network token="demo" />);
  await waitFor(() => expect(screen.getByTestId("egress-enabled-toggle")).not.toBeChecked());
  expect(screen.getByTestId("egress-state")).toHaveTextContent(/BLOCKED/i);
  expect(screen.getByTestId("egress-hosts-input")).toBeDisabled();
  expect(screen.getByTestId("egress-risk-note")).toBeInTheDocument();
});

test("enabling egress requires an inline confirm", async () => {
  mockLoad();
  render(<Network token="demo" />);
  await waitFor(() => expect(screen.getByTestId("egress-enabled-toggle")).toBeInTheDocument());

  fireEvent.click(screen.getByTestId("egress-enabled-toggle"));
  // Not committed yet — a confirm appears and the toggle stays off.
  expect(screen.getByTestId("egress-confirm")).toBeInTheDocument();
  expect(screen.getByTestId("egress-enabled-toggle")).not.toBeChecked();

  fireEvent.click(screen.getByTestId("egress-confirm-yes"));
  expect(screen.getByTestId("egress-enabled-toggle")).toBeChecked();
  // Enabled + empty list = still blocked, shown amber.
  expect(screen.getByTestId("egress-state")).toHaveTextContent(/no hosts are allowed/i);
});

test("rejects non-bare hosts and blocks save", async () => {
  mockLoad({ egress_enabled: true });
  render(<Network token="demo" />);
  await waitFor(() => expect(screen.getByTestId("egress-hosts-input")).toBeEnabled());

  fireEvent.change(screen.getByTestId("egress-hosts-input"), {
    target: { value: "https://evil.com/path" },
  });
  expect(screen.getByTestId("egress-hosts-error")).toBeInTheDocument();
  expect(screen.getByTestId("network-save")).toBeDisabled();
});

test("saves a valid allowlist via PUT settings", async () => {
  mockLoad({ egress_enabled: true });
  const save = vi.spyOn(api, "saveSettings").mockResolvedValue(SETTINGS);
  render(<Network token="demo" />);
  await waitFor(() => expect(screen.getByTestId("egress-hosts-input")).toBeEnabled());

  fireEvent.change(screen.getByTestId("egress-hosts-input"), {
    target: { value: "api.example.com, files.example.org" },
  });
  expect(screen.getByTestId("egress-state")).toHaveTextContent(/permitted to: api.example.com/i);
  fireEvent.click(screen.getByTestId("network-save"));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith("demo", {
      ...SETTINGS,
      egress_enabled: true,
      allowed_egress_hosts: ["api.example.com", "files.example.org"],
    }),
  );
});

test("surfaces a load error", async () => {
  vi.spyOn(api, "fetchSettings").mockRejectedValue(new Error("fetch settings failed: 503"));
  render(<Network token="demo" />);
  await waitFor(() => expect(screen.getByTestId("network-error")).toHaveTextContent(/503/));
});
