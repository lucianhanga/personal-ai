import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { Security } from "./Security";
import * as api from "./api";
import type { TenantSettings } from "./api";

afterEach(() => vi.restoreAllMocks());

const SETTINGS = {
  egress_enabled: null,
  allowed_egress_hosts: null,
  tool_approval_required: null,
  agent_human_gate: null,
  agent_egress_gate: null,
} as unknown as TenantSettings;

const DEFAULTS = {
  egress_enabled: false,
  allowed_egress_hosts: [],
  tool_approval_required: false,
  agent_human_gate: false,
  agent_egress_gate: false,
} as unknown as api.TenantSettingsDefaults;

function mockLoad(settings: Partial<TenantSettings> = {}): void {
  vi.spyOn(api, "fetchSettings").mockResolvedValue({ settings: { ...SETTINGS, ...settings }, defaults: DEFAULTS });
}

test("renders the approvals and network egress cards after load", async () => {
  mockLoad();
  render(<Security token="demo" />);
  await waitFor(() => expect(screen.getByTestId("security-approvals")).toBeInTheDocument());
  expect(screen.getByTestId("security-tool-approval")).toBeInTheDocument();
  expect(screen.getByTestId("security-answer-gate")).toBeInTheDocument();
  expect(screen.getByTestId("security-egress-gate")).toBeInTheDocument();
  expect(screen.getByTestId("security-network")).toBeInTheDocument();
});

test("toggling the high-risk tool-approval policy marks dirty and persists", async () => {
  mockLoad();
  const saveSettings = vi.spyOn(api, "saveSettings").mockResolvedValue({ ...SETTINGS, tool_approval_required: true });
  render(<Security token="demo" />);
  await waitFor(() => expect(screen.getByTestId("security-tool-approval")).toBeInTheDocument());

  fireEvent.click(screen.getByTestId("security-tool-approval"));
  expect(screen.getByTestId("security-dirty")).toBeInTheDocument();

  fireEvent.click(screen.getByTestId("security-save"));
  await waitFor(() => expect(saveSettings).toHaveBeenCalled());
  expect(saveSettings.mock.calls[0][1].tool_approval_required).toBe(true);
});

test("warns that tools will fail when the network-host gate is off, and clears it when on", async () => {
  mockLoad();
  render(<Security token="demo" />);
  await waitFor(() => expect(screen.getByTestId("security-egress-gate")).toBeInTheDocument());
  // Default (unchecked) -> the warning is shown.
  expect(screen.getByTestId("security-egress-gate-warning")).toBeInTheDocument();
  // Checking the gate removes the warning.
  fireEvent.click(screen.getByTestId("security-egress-gate"));
  expect(screen.queryByTestId("security-egress-gate-warning")).not.toBeInTheDocument();
});

test("the egress-approval gate persists independently of the answer gate", async () => {
  mockLoad();
  const saveSettings = vi.spyOn(api, "saveSettings").mockResolvedValue(SETTINGS);
  render(<Security token="demo" />);
  await waitFor(() => expect(screen.getByTestId("security-egress-gate")).toBeInTheDocument());

  fireEvent.click(screen.getByTestId("security-egress-gate"));
  fireEvent.click(screen.getByTestId("security-save"));
  await waitFor(() => expect(saveSettings).toHaveBeenCalled());
  const sent = saveSettings.mock.calls[0][1];
  expect(sent.agent_egress_gate).toBe(true);
  expect(sent.agent_human_gate).toBeNull(); // untouched -> not flipped
});

test("adding a valid host creates a ticked entity; saving persists the allow-list", async () => {
  mockLoad();
  const saveSettings = vi.spyOn(api, "saveSettings").mockResolvedValue(SETTINGS);
  render(<Security token="demo" />);
  await waitFor(() => expect(screen.getByTestId("egress-hosts-input")).toBeInTheDocument());

  fireEvent.change(screen.getByTestId("egress-hosts-input"), { target: { value: "api.example.com" } });
  fireEvent.click(screen.getByTestId("egress-hosts-add"));
  expect(screen.getByTestId("egress-host-api.example.com")).toHaveTextContent("✓");

  fireEvent.click(screen.getByTestId("security-save"));
  await waitFor(() => expect(saveSettings).toHaveBeenCalled());
  expect(saveSettings.mock.calls[0][1].allowed_egress_hosts).toEqual(["api.example.com"]);
});

test("an invalid-DNS host shows an x marker and blocks save", async () => {
  mockLoad();
  render(<Security token="demo" />);
  await waitFor(() => expect(screen.getByTestId("egress-hosts-input")).toBeInTheDocument());

  fireEvent.change(screen.getByTestId("egress-hosts-input"), { target: { value: "nope" } });
  fireEvent.click(screen.getByTestId("egress-hosts-add"));

  expect(screen.getByTestId("egress-host-nope")).toHaveTextContent("✗");
  expect(screen.getByTestId("egress-hosts-invalid")).toBeInTheDocument();
  expect(screen.getByTestId("security-save")).toBeDisabled();
});

test("the x button removes a host entity", async () => {
  mockLoad({ egress_enabled: true, allowed_egress_hosts: ["api.example.com", "files.example.org"] });
  render(<Security token="demo" />);
  await waitFor(() => expect(screen.getByTestId("egress-host-api.example.com")).toBeInTheDocument());

  fireEvent.click(screen.getByTestId("egress-host-remove-api.example.com"));
  expect(screen.queryByTestId("egress-host-api.example.com")).not.toBeInTheDocument();
  expect(screen.getByTestId("egress-host-files.example.org")).toBeInTheDocument();
});

test("enabling outbound egress requires an explicit confirm", async () => {
  mockLoad();
  render(<Security token="demo" />);
  await waitFor(() => expect(screen.getByTestId("egress-enabled-toggle")).toBeInTheDocument());

  fireEvent.click(screen.getByTestId("egress-enabled-toggle"));
  expect(screen.getByTestId("egress-confirm")).toBeInTheDocument();
  fireEvent.click(screen.getByTestId("egress-confirm-yes"));
  expect(screen.getByTestId("security-dirty")).toBeInTheDocument();
});
