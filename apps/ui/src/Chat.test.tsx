import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { Chat } from "./Chat";
import * as api from "./api";

afterEach(() => vi.restoreAllMocks());

const MODELS = {
  defaultModel: "qwen3.6:35b-a3b",
  models: [
    {
      name: "qwen3.6:35b-a3b",
      local: true,
      capabilities: {
        text: true,
        vision: true,
        embeddings: false,
        tool_calling: true,
        structured_output: true,
        thinking: true,
        max_context_tokens: 262144,
      },
    },
  ],
};

test("loads models and shows the default + capability badges", async () => {
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe(
      "qwen3.6:35b-a3b",
    ),
  );
  expect(screen.getByTestId("model-caps")).toHaveTextContent(/vision/);
  expect(screen.getByTestId("model-caps")).toHaveTextContent(/tools/);
});

test("sends a message and streams the assistant reply", async () => {
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "streamChat").mockImplementation(async (_params, onDelta) => {
    for (const tok of ["Hello", " ", "there"]) onDelta(tok);
  });

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("model-select")).toBeInTheDocument());

  fireEvent.change(screen.getByTestId("composer"), { target: { value: "hi" } });
  fireEvent.click(screen.getByTestId("send"));

  await waitFor(() => expect(screen.getByTestId("msg-user")).toHaveTextContent("hi"));
  await waitFor(() =>
    expect(screen.getByTestId("msg-assistant")).toHaveTextContent("Hello there"),
  );
});

test("surfaces an error when models cannot be loaded", async () => {
  vi.spyOn(api, "fetchModels").mockRejectedValue(new Error("401"));
  render(<Chat token="bad" />);
  await waitFor(() => expect(screen.getByTestId("chat-error")).toHaveTextContent(/401/));
});
