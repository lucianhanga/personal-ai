import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { Agents } from "./Agents";
import * as api from "./api";
import type { AgentConfigView, TenantSettings } from "./api";

afterEach(() => vi.restoreAllMocks());

const SETTINGS: TenantSettings = {
  model_provider: null,
  default_model: null,
  default_reasoning: null,
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
  rich_output_enabled: null,
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

const MODEL_INFO: api.ModelInfo = {
  name: "qwen3:7b",
  local: true,
  capabilities: {
    text: true,
    vision: false,
    embeddings: false,
    tool_calling: true,
    structured_output: true,
    thinking: false,
    max_context_tokens: null,
  },
};

test("per-agent reasoning dropdown defaults to Inherit and marks dirty on change", async () => {
  mockLoad({ agent_mode: "multi" });
  vi.spyOn(api, "fetchModels").mockResolvedValue({ defaultModel: "", models: [] });
  const saveAgents = vi.spyOn(api, "saveAgentConfig").mockResolvedValue({ agents: [] });
  vi.spyOn(api, "saveSettings").mockResolvedValue(SETTINGS);

  render(<Agents token="demo" />);
  await waitFor(() => expect(screen.getByTestId("agents-card-planner")).toBeInTheDocument());

  const select = screen.getByTestId("agents-reasoning-planner") as HTMLSelectElement;
  expect(select.value).toBe(""); // Inherit by default

  fireEvent.change(select, { target: { value: "high" } });
  expect(screen.getByTestId("agents-dirty")).toBeInTheDocument();

  fireEvent.click(screen.getByTestId("agents-save"));
  await waitFor(() => expect(saveAgents).toHaveBeenCalled());
  const sentConfig = saveAgents.mock.calls[0][1];
  const planner = sentConfig.agents.find((a: { name: string }) => a.name === "planner");
  expect(planner?.reasoning).toBe("high");
});

test("per-agent model dropdown lists available models and sends the selected model on save", async () => {
  mockLoad({ agent_mode: "multi" });
  vi.spyOn(api, "fetchModels").mockResolvedValue({
    defaultModel: "qwen3:7b",
    models: [MODEL_INFO],
  });
  const saveAgents = vi.spyOn(api, "saveAgentConfig").mockResolvedValue({ agents: [] });
  vi.spyOn(api, "saveSettings").mockResolvedValue(SETTINGS);

  render(<Agents token="demo" />);
  await waitFor(() => expect(screen.getByTestId("agents-card-planner")).toBeInTheDocument());

  // Wait for model options to populate (separate async effect).
  await waitFor(() =>
    expect(screen.getByTestId("agents-model-planner")).toContainHTML("qwen3:7b"),
  );

  const select = screen.getByTestId("agents-model-planner") as HTMLSelectElement;
  expect(select.value).toBe(""); // Inherit by default

  fireEvent.change(select, { target: { value: "qwen3:7b" } });

  fireEvent.click(screen.getByTestId("agents-save"));
  await waitFor(() => expect(saveAgents).toHaveBeenCalled());
  const sentConfig = saveAgents.mock.calls[0][1];
  const planner = sentConfig.agents.find((a: { name: string }) => a.name === "planner");
  expect(planner?.model).toBe("qwen3:7b");
});

test("loading saved per-agent reasoning and model restores the dropdown values", async () => {
  const viewWithOverrides: api.AgentConfigView = {
    ...VIEW,
    config: {
      agents: [{ name: "planner", prompt: null, disabled_tools: [], reasoning: "medium", model: "qwen3:7b" }],
    },
  };
  mockLoad({ agent_mode: "multi" }, viewWithOverrides);
  vi.spyOn(api, "fetchModels").mockResolvedValue({
    defaultModel: "qwen3:7b",
    models: [MODEL_INFO],
  });

  render(<Agents token="demo" />);
  await waitFor(() => expect(screen.getByTestId("agents-card-planner")).toBeInTheDocument());
  await waitFor(() =>
    expect((screen.getByTestId("agents-reasoning-planner") as HTMLSelectElement).value).toBe("medium"),
  );
  await waitFor(() =>
    expect((screen.getByTestId("agents-model-planner") as HTMLSelectElement).value).toBe("qwen3:7b"),
  );
});

test("Defaults section loads current default_model from settings", async () => {
  mockLoad({ default_model: "qwen3:7b" });
  vi.spyOn(api, "fetchModels").mockResolvedValue({
    defaultModel: "qwen3:7b",
    models: [MODEL_INFO],
  });

  render(<Agents token="demo" />);
  await waitFor(() => expect(screen.getByTestId("agents-defaults")).toBeInTheDocument());
  await waitFor(() =>
    expect((screen.getByTestId("agents-default-model") as HTMLSelectElement).value).toBe("qwen3:7b"),
  );
});

test("changing default model marks dirty and saves the updated default_model", async () => {
  mockLoad({ default_model: null });
  vi.spyOn(api, "fetchModels").mockResolvedValue({
    defaultModel: "qwen3:7b",
    models: [MODEL_INFO],
  });
  const saveSettings = vi.spyOn(api, "saveSettings").mockResolvedValue({ ...SETTINGS, default_model: "qwen3:7b", default_reasoning: null });
  vi.spyOn(api, "saveAgentConfig").mockResolvedValue({ agents: [] });

  render(<Agents token="demo" />);
  await waitFor(() =>
    expect(screen.getByTestId("agents-default-model")).toContainHTML("qwen3:7b"),
  );

  fireEvent.change(screen.getByTestId("agents-default-model"), { target: { value: "qwen3:7b" } });
  expect(screen.getByTestId("agents-dirty")).toBeInTheDocument();

  fireEvent.click(screen.getByTestId("agents-save"));
  await waitFor(() => expect(saveSettings).toHaveBeenCalled());
  const sentSettings = saveSettings.mock.calls[0][1] as api.TenantSettings;
  expect(sentSettings.default_model).toBe("qwen3:7b");
});

test("changing default reasoning marks dirty and saves the updated default_reasoning", async () => {
  mockLoad({ default_reasoning: null });
  vi.spyOn(api, "fetchModels").mockResolvedValue({ defaultModel: "", models: [] });
  const saveSettings = vi.spyOn(api, "saveSettings").mockResolvedValue({ ...SETTINGS, default_reasoning: "high" });
  vi.spyOn(api, "saveAgentConfig").mockResolvedValue({ agents: [] });

  render(<Agents token="demo" />);
  await waitFor(() => expect(screen.getByTestId("agents-default-reasoning")).toBeInTheDocument());

  const select = screen.getByTestId("agents-default-reasoning") as HTMLSelectElement;
  expect(select.value).toBe(""); // null -> empty = "Inherit (server default)"

  fireEvent.change(select, { target: { value: "high" } });
  expect(screen.getByTestId("agents-dirty")).toBeInTheDocument();

  fireEvent.click(screen.getByTestId("agents-save"));
  await waitFor(() => expect(saveSettings).toHaveBeenCalled());
  const sentSettings = saveSettings.mock.calls[0][1] as api.TenantSettings;
  expect(sentSettings.default_reasoning).toBe("high");
});

test("Defaults section shows a Provider select with server-default option", async () => {
  mockLoad({ model_provider: null });
  vi.spyOn(api, "fetchModels").mockResolvedValue({ defaultModel: "", models: [] });

  render(<Agents token="demo" />);
  await waitFor(() => expect(screen.getByTestId("agents-default-provider")).toBeInTheDocument());

  const select = screen.getByTestId("agents-default-provider") as HTMLSelectElement;
  expect(select.value).toBe(""); // null -> empty = "Use server default"
});

test("Defaults section loads saved model_provider from settings", async () => {
  mockLoad({ model_provider: "openai_compat" });
  vi.spyOn(api, "fetchModels").mockResolvedValue({ defaultModel: "", models: [] });

  render(<Agents token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("agents-default-provider") as HTMLSelectElement).value).toBe(
      "openai_compat",
    ),
  );
});

test("changing default provider marks dirty and saves the updated model_provider", async () => {
  mockLoad({ model_provider: null });
  vi.spyOn(api, "fetchModels").mockResolvedValue({ defaultModel: "", models: [] });
  const saveSettings = vi.spyOn(api, "saveSettings").mockResolvedValue({
    ...SETTINGS,
    model_provider: "ollama",
  });
  vi.spyOn(api, "saveAgentConfig").mockResolvedValue({ agents: [] });

  render(<Agents token="demo" />);
  await waitFor(() => expect(screen.getByTestId("agents-default-provider")).toBeInTheDocument());

  fireEvent.change(screen.getByTestId("agents-default-provider"), {
    target: { value: "ollama" },
  });
  expect(screen.getByTestId("agents-dirty")).toBeInTheDocument();

  fireEvent.click(screen.getByTestId("agents-save"));
  await waitFor(() => expect(saveSettings).toHaveBeenCalled());
  const sentSettings = saveSettings.mock.calls[0][1] as api.TenantSettings;
  expect(sentSettings.model_provider).toBe("ollama");
});

test("Execution accuracy mode is tri-state and persists on save (moved from Preferences #513)", async () => {
  mockLoad({ agent_accuracy_mode: null });
  vi.spyOn(api, "fetchModels").mockResolvedValue({ defaultModel: "", models: [] });
  const saveSettings = vi
    .spyOn(api, "saveSettings")
    .mockResolvedValue({ ...SETTINGS, agent_accuracy_mode: "accurate" });
  vi.spyOn(api, "saveAgentConfig").mockResolvedValue({ agents: [] });

  render(<Agents token="demo" />);
  await waitFor(() => expect(screen.getByTestId("agents-accuracy-mode")).toBeInTheDocument());

  const select = screen.getByTestId("agents-accuracy-mode") as HTMLSelectElement;
  expect(select.value).toBe(""); // null -> empty = "Inherit (server default)"

  fireEvent.change(select, { target: { value: "accurate" } });
  expect(screen.getByTestId("agents-dirty")).toBeInTheDocument();

  fireEvent.click(screen.getByTestId("agents-save"));
  await waitFor(() => expect(saveSettings).toHaveBeenCalled());
  const sentSettings = saveSettings.mock.calls[0][1] as api.TenantSettings;
  expect(sentSettings.agent_accuracy_mode).toBe("accurate");
});

test("Execution max-iterations and timeout persist their numeric overrides on save", async () => {
  mockLoad({ agent_max_iterations: null, agent_timeout_seconds: null });
  vi.spyOn(api, "fetchModels").mockResolvedValue({ defaultModel: "", models: [] });
  const saveSettings = vi.spyOn(api, "saveSettings").mockResolvedValue(SETTINGS);
  vi.spyOn(api, "saveAgentConfig").mockResolvedValue({ agents: [] });

  render(<Agents token="demo" />);
  await waitFor(() => expect(screen.getByTestId("agents-max-iterations")).toBeInTheDocument());

  fireEvent.change(screen.getByTestId("agents-max-iterations"), { target: { value: "12" } });
  fireEvent.change(screen.getByTestId("agents-timeout-seconds"), { target: { value: "600" } });
  expect(screen.getByTestId("agents-dirty")).toBeInTheDocument();

  fireEvent.click(screen.getByTestId("agents-save"));
  await waitFor(() => expect(saveSettings).toHaveBeenCalled());
  const sentSettings = saveSettings.mock.calls[0][1] as api.TenantSettings;
  expect(sentSettings.agent_max_iterations).toBe(12);
  expect(sentSettings.agent_timeout_seconds).toBe(600);
});
