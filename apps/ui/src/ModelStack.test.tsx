import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { ModelStack } from "./ModelStack";
import * as api from "./api";
import type { TenantSettings } from "./api";

afterEach(() => vi.restoreAllMocks());

// The combined dropdowns encode a choice as `provider<US>model` (mirrors ModelStack.tsx SEP).
const SEP = "\u001f";

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
  ner_model: null,
  rerank_enabled: null,
  rerank_model: null,
  agent_mode: null,
  agent_graph_enabled: null,
  agent_human_gate: null,
  agent_egress_gate: null,
  agent_accuracy_mode: null,
  agent_verifier_check: null,
  tool_approval_required: null,
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

const CHAT: api.ModelInfo = {
  name: "qwen3:7b",
  local: true,
  capabilities: { text: true, vision: false, embeddings: false, tool_calling: true, structured_output: true, thinking: false, max_context_tokens: null },
};
const EMBED: api.ModelInfo = {
  name: "qwen3-embedding:0.6b",
  local: true,
  capabilities: { text: false, vision: false, embeddings: true, tool_calling: false, structured_output: false, thinking: false, max_context_tokens: null },
};

// Deployment defaults shown read-only in the "Server defaults" card.
const DEFAULTS = {
  ...SETTINGS,
  model_provider: "ollama",
  default_model: "qwen3.6:27b",
  default_reasoning: "low",
  embed_provider: "ollama",
  embed_model: "qwen3-embedding:0.6b",
  rerank_enabled: false,
  rerank_model: "Qwen/Qwen3-Reranker-0.6B",
  ner_model: "qwen3:14b",
} as unknown as api.TenantSettingsDefaults;

function mockLoad(settings: Partial<TenantSettings> = {}): void {
  vi.spyOn(api, "fetchSettings").mockResolvedValue({ settings: { ...SETTINGS, ...settings }, defaults: DEFAULTS });
  vi.spyOn(api, "fetchProviders").mockResolvedValue({ default: "ollama", providers: ["ollama"] });
  vi.spyOn(api, "fetchModels").mockResolvedValue({ defaultModel: "", models: [CHAT, EMBED] });
}

test("renders a row per task after load", async () => {
  mockLoad();
  render(<ModelStack token="demo" />);
  await waitFor(() => expect(screen.getByTestId("model-stack-chat")).toBeInTheDocument());
  expect(screen.getByTestId("model-stack-embed")).toBeInTheDocument();
  expect(screen.getByTestId("model-stack-rerank")).toBeInTheDocument();
  expect(screen.getByTestId("model-stack-ner")).toBeInTheDocument();
});

test("the Server defaults card shows the deployment values read-only", async () => {
  mockLoad();
  render(<ModelStack token="demo" />);
  await waitFor(() => expect(screen.getByTestId("model-stack-default-chat")).toBeInTheDocument());
  expect(screen.getByTestId("model-stack-default-chat")).toHaveTextContent("ollama / qwen3.6:27b");
  expect(screen.getByTestId("model-stack-default-embed")).toHaveTextContent("ollama / qwen3-embedding:0.6b");
  expect(screen.getByTestId("model-stack-default-rerank")).toHaveTextContent("Off");
  expect(screen.getByTestId("model-stack-default-ner")).toHaveTextContent("ollama / qwen3:14b");
});

test("chat dropdown loads the saved provider/model as one combined value", async () => {
  mockLoad({ model_provider: "ollama", default_model: "qwen3:7b" });
  render(<ModelStack token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-stack-chat") as HTMLSelectElement).value).toBe("ollama" + SEP + "qwen3:7b"),
  );
});

test("changing the chat dropdown saves BOTH model_provider and default_model", async () => {
  mockLoad();
  const saveSettings = vi.spyOn(api, "saveSettings").mockResolvedValue(SETTINGS);
  render(<ModelStack token="demo" />);
  await waitFor(() => expect(screen.getByTestId("model-stack-chat")).toContainHTML("qwen3:7b"));

  fireEvent.change(screen.getByTestId("model-stack-chat"), { target: { value: "ollama" + SEP + "qwen3:7b" } });
  expect(screen.getByTestId("model-stack-dirty")).toBeInTheDocument();

  fireEvent.click(screen.getByTestId("model-stack-save"));
  await waitFor(() => expect(saveSettings).toHaveBeenCalled());
  const sent = saveSettings.mock.calls[0][1];
  expect(sent.model_provider).toBe("ollama");
  expect(sent.default_model).toBe("qwen3:7b");
});

test("reasoning select persists default_reasoning", async () => {
  mockLoad();
  const saveSettings = vi.spyOn(api, "saveSettings").mockResolvedValue(SETTINGS);
  render(<ModelStack token="demo" />);
  await waitFor(() => expect(screen.getByTestId("model-stack-reasoning")).toBeInTheDocument());

  const select = screen.getByTestId("model-stack-reasoning") as HTMLSelectElement;
  expect(select.value).toBe(""); // null -> "Use server default"
  fireEvent.change(select, { target: { value: "high" } });

  fireEvent.click(screen.getByTestId("model-stack-save"));
  await waitFor(() => expect(saveSettings).toHaveBeenCalled());
  expect(saveSettings.mock.calls[0][1].default_reasoning).toBe("high");
});

test("embeddings dropdown saves embed_provider and embed_model", async () => {
  mockLoad();
  const saveSettings = vi.spyOn(api, "saveSettings").mockResolvedValue(SETTINGS);
  render(<ModelStack token="demo" />);
  await waitFor(() => expect(screen.getByTestId("model-stack-embed")).toContainHTML("qwen3-embedding:0.6b"));

  fireEvent.change(screen.getByTestId("model-stack-embed"), {
    target: { value: "ollama" + SEP + "qwen3-embedding:0.6b" },
  });
  fireEvent.click(screen.getByTestId("model-stack-save"));
  await waitFor(() => expect(saveSettings).toHaveBeenCalled());
  const sent = saveSettings.mock.calls[0][1];
  expect(sent.embed_provider).toBe("ollama");
  expect(sent.embed_model).toBe("qwen3-embedding:0.6b");
});

test("reranker 'Off' disables the stage (rerank_enabled=false, model cleared)", async () => {
  mockLoad({ rerank_enabled: true, rerank_model: "Qwen/Qwen3-Reranker-0.6B" });
  const saveSettings = vi.spyOn(api, "saveSettings").mockResolvedValue(SETTINGS);
  render(<ModelStack token="demo" />);
  await waitFor(() => expect(screen.getByTestId("model-stack-rerank")).toBeInTheDocument());

  fireEvent.change(screen.getByTestId("model-stack-rerank"), { target: { value: "off" } });
  fireEvent.click(screen.getByTestId("model-stack-save"));
  await waitFor(() => expect(saveSettings).toHaveBeenCalled());
  const sent = saveSettings.mock.calls[0][1];
  expect(sent.rerank_enabled).toBe(false);
  expect(sent.rerank_model).toBeNull();
});

test("picking a reranker model enables the stage and stores the id", async () => {
  mockLoad();
  const saveSettings = vi.spyOn(api, "saveSettings").mockResolvedValue(SETTINGS);
  render(<ModelStack token="demo" />);
  await waitFor(() => expect(screen.getByTestId("model-stack-rerank")).toBeInTheDocument());

  fireEvent.change(screen.getByTestId("model-stack-rerank"), { target: { value: "Qwen/Qwen3-Reranker-4B" } });
  fireEvent.click(screen.getByTestId("model-stack-save"));
  await waitFor(() => expect(saveSettings).toHaveBeenCalled());
  const sent = saveSettings.mock.calls[0][1];
  expect(sent.rerank_enabled).toBe(true);
  expect(sent.rerank_model).toBe("Qwen/Qwen3-Reranker-4B");
});

test("NER dropdown saves ner_model (Ollama, model only)", async () => {
  mockLoad();
  const saveSettings = vi.spyOn(api, "saveSettings").mockResolvedValue(SETTINGS);
  render(<ModelStack token="demo" />);
  await waitFor(() => expect(screen.getByTestId("model-stack-ner")).toContainHTML("qwen3:7b"));

  fireEvent.change(screen.getByTestId("model-stack-ner"), { target: { value: "ollama" + SEP + "qwen3:7b" } });
  fireEvent.click(screen.getByTestId("model-stack-save"));
  await waitFor(() => expect(saveSettings).toHaveBeenCalled());
  expect(saveSettings.mock.calls[0][1].ner_model).toBe("qwen3:7b");
});
