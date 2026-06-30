import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { Preferences } from "./Preferences";
import * as api from "./api";
import type { TenantSettings, TenantSettingsDefaults } from "./api";

afterEach(() => vi.restoreAllMocks());

const EMPTY: TenantSettings = {
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

const DEFAULTS: TenantSettingsDefaults = {
  model_provider: "ollama",
  default_model: "qwen3.6:35b-a3b",
  default_reasoning: "low",
  ollama_host: "http://127.0.0.1:11434",
  ollama_num_ctx: 32768,
  ollama_keep_alive: "30m",
  embed_provider: "ollama",
  embed_model: "qwen3-embedding:0.6b",
  openai_base_url: "https://api.openai.com/v1",
  ner_model: "qwen3:14b",
  rerank_enabled: false,
  rerank_model: "Qwen/Qwen3-Reranker-0.6B",
  agent_mode: "single",
  agent_graph_enabled: false,
  agent_human_gate: false,
  agent_egress_gate: false,
  agent_accuracy_mode: "standard",
  agent_verifier_check: true,
  tool_approval_required: false,
  agent_max_iterations: 8,
  agent_timeout_seconds: 300,
  memory_enabled: true,
  grounding_enabled: true,
  rich_output_enabled: true,
  max_upload_bytes: 10000000,
  egress_enabled: false,
  allowed_egress_hosts: [],
  transcribe_provider: "local",
  transcribe_enabled: false,
  transcribe_base_url: "",
  transcribe_model: "whisper-1",
  transcribe_language: "auto",
  tts_enabled: false,
};

function mockLoad(settings: TenantSettings = EMPTY): void {
  vi.spyOn(api, "fetchSettings").mockResolvedValue({ settings, defaults: DEFAULTS });
}

test("shows the deployment default as the placeholder when unset", async () => {
  mockLoad();
  render(<Preferences token="demo" />);
  // The model field moved to the top bar; ollama_host is a representative remaining text field.
  await waitFor(() =>
    expect(screen.getByTestId("preferences-ollama_host")).toHaveAttribute(
      "placeholder",
      "http://127.0.0.1:11434",
    ),
  );
});

test("editing a field saves only the override", async () => {
  mockLoad();
  const save = vi
    .spyOn(api, "saveSettings")
    .mockResolvedValue({ ...EMPTY, ollama_host: "http://gpu:11434" });
  render(<Preferences token="demo" />);
  await waitFor(() => expect(screen.getByTestId("preferences-ollama_host")).toBeInTheDocument());

  fireEvent.change(screen.getByTestId("preferences-ollama_host"), {
    target: { value: "http://gpu:11434" },
  });
  expect(screen.getByTestId("preferences-dirty")).toBeInTheDocument();

  fireEvent.click(screen.getByTestId("preferences-save"));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith("demo", { ...EMPTY, ollama_host: "http://gpu:11434" }),
  );
  await waitFor(() => expect(screen.getByTestId("preferences-saved")).toBeInTheDocument());
});

test("reset clears every override back to null", async () => {
  mockLoad({ ...EMPTY, ollama_host: "http://gpu:11434", agent_accuracy_mode: "accurate" });
  const save = vi.spyOn(api, "saveSettings").mockResolvedValue(EMPTY);
  render(<Preferences token="demo" />);
  await waitFor(() =>
    expect(screen.getByTestId("preferences-ollama_host")).toHaveValue("http://gpu:11434"),
  );

  fireEvent.click(screen.getByTestId("preferences-reset"));
  fireEvent.click(screen.getByTestId("preferences-save"));
  await waitFor(() => expect(save).toHaveBeenCalledWith("demo", EMPTY));
});

test("surfaces a load error", async () => {
  vi.spyOn(api, "fetchSettings").mockRejectedValue(new Error("fetch settings failed: 503"));
  render(<Preferences token="demo" />);
  await waitFor(() => expect(screen.getByTestId("preferences-error")).toHaveTextContent(/503/));
});
