import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { Preferences } from "./Preferences";
import * as api from "./api";
import type { TenantSettings, TenantSettingsDefaults } from "./api";

afterEach(() => vi.restoreAllMocks());

const EMPTY: TenantSettings = {
  model_provider: null,
  default_model: null,
  ollama_host: null,
  ollama_num_ctx: null,
  ollama_keep_alive: null,
  embed_provider: null,
  embed_model: null,
  openai_base_url: null,
  agent_graph_enabled: null,
  agent_human_gate: null,
  agent_accuracy_mode: null,
  agent_max_iterations: null,
  memory_enabled: null,
  grounding_enabled: null,
  max_upload_bytes: null,
};

const DEFAULTS: TenantSettingsDefaults = {
  model_provider: "ollama",
  default_model: "qwen3.6:35b-a3b",
  ollama_host: "http://127.0.0.1:11434",
  ollama_num_ctx: 32768,
  ollama_keep_alive: "30m",
  embed_provider: "ollama",
  embed_model: "mxbai-embed-large",
  openai_base_url: "https://api.openai.com/v1",
  agent_graph_enabled: false,
  agent_human_gate: false,
  agent_accuracy_mode: "standard",
  agent_max_iterations: 8,
  memory_enabled: true,
  grounding_enabled: true,
  max_upload_bytes: 10000000,
};

function mockLoad(settings: TenantSettings = EMPTY): void {
  vi.spyOn(api, "fetchSettings").mockResolvedValue({ settings, defaults: DEFAULTS });
}

test("shows the deployment default as the placeholder when unset", async () => {
  mockLoad();
  render(<Preferences token="demo" />);
  await waitFor(() =>
    expect(screen.getByTestId("preferences-default_model")).toHaveAttribute(
      "placeholder",
      "qwen3.6:35b-a3b",
    ),
  );
});

test("editing a field saves only the override", async () => {
  mockLoad();
  const save = vi.spyOn(api, "saveSettings").mockResolvedValue({ ...EMPTY, default_model: "qwen3:14b" });
  render(<Preferences token="demo" />);
  await waitFor(() => expect(screen.getByTestId("preferences-default_model")).toBeInTheDocument());

  fireEvent.change(screen.getByTestId("preferences-default_model"), {
    target: { value: "qwen3:14b" },
  });
  expect(screen.getByTestId("preferences-dirty")).toBeInTheDocument();

  fireEvent.click(screen.getByTestId("preferences-save"));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith("demo", { ...EMPTY, default_model: "qwen3:14b" }),
  );
  await waitFor(() => expect(screen.getByTestId("preferences-saved")).toBeInTheDocument());
});

test("the multi-agent toggle is tri-state (default/on/off)", async () => {
  mockLoad();
  const save = vi.spyOn(api, "saveSettings").mockResolvedValue({ ...EMPTY, agent_graph_enabled: true });
  render(<Preferences token="demo" />);
  await waitFor(() => expect(screen.getByTestId("preferences-agent_graph_enabled")).toBeInTheDocument());

  fireEvent.change(screen.getByTestId("preferences-agent_graph_enabled"), {
    target: { value: "on" },
  });
  fireEvent.click(screen.getByTestId("preferences-save"));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith("demo", { ...EMPTY, agent_graph_enabled: true }),
  );
});

test("reset clears every override back to null", async () => {
  mockLoad({ ...EMPTY, default_model: "qwen3:14b", agent_graph_enabled: true });
  const save = vi.spyOn(api, "saveSettings").mockResolvedValue(EMPTY);
  render(<Preferences token="demo" />);
  await waitFor(() =>
    expect(screen.getByTestId("preferences-default_model")).toHaveValue("qwen3:14b"),
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
