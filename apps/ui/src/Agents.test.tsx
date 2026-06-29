import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { Agents } from "./Agents";
import * as api from "./api";
import type { AgentConfigView, TenantSettings } from "./api";

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
  agent_verifier_check: null,
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
  tts_enabled: null,
};

const VIEW: AgentConfigView = {
  config: { agents: [] },
  defaults: {
    planner: "You are the planner.",
    researcher: "You are the researcher.",
    critic: "You are the critic.",
    verifier: "You are the verifier.",
  },
  agents: [
    { name: "planner", uses_tools: false },
    { name: "researcher", uses_tools: true },
    { name: "critic", uses_tools: false },
    { name: "verifier", uses_tools: false },
  ],
  available_tools: ["web_search", "http_fetch"],
};

function mockLoad(settings: Partial<TenantSettings> = {}, view: AgentConfigView = VIEW): void {
  vi.spyOn(api, "fetchSettings").mockResolvedValue({
    settings: { ...SETTINGS, ...settings },
    // defaults aren't used by Agents; a minimal stub keeps the type happy.
    defaults: {} as never,
  });
  vi.spyOn(api, "fetchAgentConfig").mockResolvedValue(view);
}

test("single mode hides the per-agent cards", async () => {
  mockLoad({ agent_mode: "single" });
  render(<Agents token="demo" />);
  await waitFor(() => expect(screen.getByTestId("agents-mode")).toBeInTheDocument());
  expect(screen.queryByTestId("agents-card-planner")).not.toBeInTheDocument();
});

test("custom mode option is disabled", async () => {
  mockLoad();
  render(<Agents token="demo" />);
  await waitFor(() => expect(screen.getByTestId("agents-mode-custom")).toBeDisabled());
});

test("multi mode shows each agent; only the researcher has tools", async () => {
  mockLoad({ agent_mode: "multi" });
  render(<Agents token="demo" />);
  await waitFor(() => expect(screen.getByTestId("agents-card-researcher")).toBeInTheDocument());
  expect(screen.getByTestId("agents-tools-researcher")).toBeInTheDocument();
  expect(screen.queryByTestId("agents-tools-planner")).not.toBeInTheDocument();
  // The default prompt shows as the textarea placeholder.
  expect(screen.getByTestId("agents-prompt-planner")).toHaveAttribute(
    "placeholder",
    "You are the planner.",
  );
});

test("editing a prompt and disabling a tool saves settings + agent config", async () => {
  mockLoad({ agent_mode: "multi" });
  const saveSettings = vi.spyOn(api, "saveSettings").mockResolvedValue(SETTINGS);
  const saveAgents = vi.spyOn(api, "saveAgentConfig").mockResolvedValue({ agents: [] });
  render(<Agents token="demo" />);
  await waitFor(() => expect(screen.getByTestId("agents-card-researcher")).toBeInTheDocument());

  fireEvent.change(screen.getByTestId("agents-prompt-planner"), {
    target: { value: "Plan tersely." },
  });
  // Uncheck http_fetch for the researcher -> it becomes disabled.
  fireEvent.click(screen.getByTestId("agents-tool-researcher-http_fetch"));

  fireEvent.click(screen.getByTestId("agents-save"));
  await waitFor(() => expect(saveAgents).toHaveBeenCalled());
  expect(saveSettings).toHaveBeenCalled();
  const sentConfig = saveAgents.mock.calls[0][1];
  const planner = sentConfig.agents.find((a) => a.name === "planner");
  const researcher = sentConfig.agents.find((a) => a.name === "researcher");
  expect(planner?.prompt).toBe("Plan tersely.");
  expect(researcher?.disabled_tools).toEqual(["http_fetch"]);
});

test("switching mode to multi marks the panel dirty and persists agent_mode", async () => {
  mockLoad({ agent_mode: "single" });
  const saveSettings = vi.spyOn(api, "saveSettings").mockResolvedValue(SETTINGS);
  vi.spyOn(api, "saveAgentConfig").mockResolvedValue({ agents: [] });
  render(<Agents token="demo" />);
  await waitFor(() => expect(screen.getByTestId("agents-mode-multi")).toBeInTheDocument());

  fireEvent.click(screen.getByTestId("agents-mode-multi"));
  expect(screen.getByTestId("agents-dirty")).toBeInTheDocument();
  fireEvent.click(screen.getByTestId("agents-save"));
  await waitFor(() =>
    expect(saveSettings).toHaveBeenCalledWith("demo", { ...SETTINGS, agent_mode: "multi" }),
  );
});

test("surfaces a load error", async () => {
  vi.spyOn(api, "fetchSettings").mockRejectedValue(new Error("fetch settings failed: 503"));
  vi.spyOn(api, "fetchAgentConfig").mockResolvedValue(VIEW);
  render(<Agents token="demo" />);
  await waitFor(() => expect(screen.getByTestId("agents-error")).toHaveTextContent(/503/));
});
