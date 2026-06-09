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

function mockProviders(providers: string[] = ["ollama", "openai"], def = "ollama"): void {
  vi.spyOn(api, "fetchProviders").mockResolvedValue({ default: def, providers });
  vi.spyOn(api, "fetchFiles").mockResolvedValue([]);
  vi.spyOn(api, "fetchMemories").mockResolvedValue([]);
  // Persistence off by default (no storage); persistence tests override this.
  vi.spyOn(api, "fetchConversations").mockRejectedValue(new Error("no storage"));
}

const CONV = { id: "c1", title: "Old chat", updated_at: "2026-06-07T00:00:00Z" };

const DOC = {
  id: "d1",
  name: "geo.txt",
  mime: "text/plain",
  size_bytes: 5,
  chunk_count: 2,
  created_at: "2026-06-07T00:00:00Z",
};

test("loads providers + models and shows capability badges", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("provider-select") as HTMLSelectElement).value).toBe("ollama"),
  );
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe(
      "qwen3.6:35b-a3b",
    ),
  );
  expect(screen.getByTestId("model-caps")).toHaveTextContent(/vision/);
});

test("switching provider reloads its models", async () => {
  mockProviders();
  const fetchModels = vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("provider-select")).toBeInTheDocument());

  fireEvent.change(screen.getByTestId("provider-select"), { target: { value: "openai" } });
  await waitFor(() => expect(fetchModels).toHaveBeenCalledWith("demo", "openai"));
});

test("sends a message and streams the assistant reply", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "streamChat").mockImplementation(async (_params, onDelta) => {
    for (const tok of ["Hello", " ", "there"]) onDelta(tok);
  });

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe(
      "qwen3.6:35b-a3b",
    ),
  );

  fireEvent.change(screen.getByTestId("composer"), { target: { value: "hi" } });
  fireEvent.click(screen.getByTestId("send"));

  await waitFor(() => expect(screen.getByTestId("msg-user")).toHaveTextContent("hi"));
  await waitFor(() =>
    expect(screen.getByTestId("msg-assistant")).toHaveTextContent("Hello there"),
  );
});

test("surfaces an error when models cannot be loaded", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockRejectedValue(new Error("egress is disabled"));
  render(<Chat token="demo" />);
  await waitFor(() =>
    expect(screen.getByTestId("chat-error")).toHaveTextContent(/egress is disabled/),
  );
});

test("uploads a document, lists it, and enables RAG", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchFiles").mockResolvedValueOnce([]).mockResolvedValue([DOC]);
  const upload = vi.spyOn(api, "uploadFile").mockResolvedValue(DOC);

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("file-input")).toBeInTheDocument());

  const file = new File(["hi"], "geo.txt", { type: "text/plain" });
  fireEvent.change(screen.getByTestId("file-input"), { target: { files: [file] } });

  await waitFor(() => expect(upload).toHaveBeenCalled());
  await waitFor(() => expect(screen.getByTestId("file-list")).toHaveTextContent("geo.txt"));
  expect(screen.getByTestId("rag-toggle")).toBeChecked();
});

test("defaults 'Use my documents' on when documents already exist", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchFiles").mockResolvedValue([DOC]);

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("file-list")).toHaveTextContent("geo.txt"));
  expect(screen.getByTestId("rag-toggle")).toBeChecked();
  expect(screen.queryByTestId("rag-hint")).toBeNull();
});

test("hints when documents exist but RAG is off", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchFiles").mockResolvedValue([DOC]);

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("rag-toggle")).toBeChecked());
  fireEvent.click(screen.getByTestId("rag-toggle")); // turn it off
  expect(screen.getByTestId("rag-hint")).toBeInTheDocument();
});

test("renders citations returned with a RAG answer", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "streamChat").mockImplementation(async (_params, onDelta, onCitations) => {
    onDelta("The capital is Lisbon [1]");
    onCitations?.([{ n: 1, source_id: "d1", locator: "chunk 0", score: 0.9, name: "geo.txt" }]);
  });

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe(
      "qwen3.6:35b-a3b",
    ),
  );
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "capital?" } });
  fireEvent.click(screen.getByTestId("send"));

  await waitFor(() => expect(screen.getByTestId("citations")).toHaveTextContent("geo.txt"));
  expect(screen.getByTestId("citations")).toHaveTextContent("[1]");
});

test("shows conversations and lazily creates one on first send", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchConversations").mockResolvedValue([CONV]);
  const create = vi
    .spyOn(api, "createConversation")
    .mockResolvedValue({ id: "c2", title: "hello", updated_at: "now" });
  const stream = vi.spyOn(api, "streamChat").mockImplementation(async (_p, onDelta) => {
    onDelta("hi");
  });

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("conversations")).toBeInTheDocument());
  expect(screen.getByTestId("open-c1")).toHaveTextContent("Old chat");

  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe(
      "qwen3.6:35b-a3b",
    ),
  );
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "hello" } });
  fireEvent.click(screen.getByTestId("send"));

  await waitFor(() => expect(create).toHaveBeenCalled());
  await waitFor(() =>
    expect(stream).toHaveBeenCalledWith(
      expect.objectContaining({ conversationId: "c2" }),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
    ),
  );
});

test("shows the context meter after a turn reports usage", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "streamChat").mockImplementation(
    async (_p, onDelta, _onCit, _onTool, onUsage) => {
      onDelta("hi");
      onUsage?.({
        prompt_tokens: 4096,
        completion_tokens: 50,
        total_tokens: 4146,
        context_limit: 32768,
      });
    },
  );

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "hi" } });
  fireEvent.click(screen.getByTestId("send"));

  await waitFor(() =>
    expect(screen.getByTestId("context-meter-label")).toHaveTextContent("4,096 / 32,768"),
  );
});

test("renders tool steps when the agent uses tools", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "streamChat").mockImplementation(async (_p, onDelta, _onCit, onToolStep) => {
    onToolStep?.({ phase: "call", tool: "web_search", args: { query: "rust" } });
    onToolStep?.({ phase: "result", tool: "web_search", ok: true, output: { results: [] } });
    onDelta("Here's what I found.");
  });

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe(
      "qwen3.6:35b-a3b",
    ),
  );
  fireEvent.click(screen.getByTestId("tools-toggle"));
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "search rust" } });
  fireEvent.click(screen.getByTestId("send"));

  await waitFor(() => expect(screen.getByTestId("tool-steps")).toHaveTextContent("web_search"));
  await waitFor(() =>
    expect(screen.getByTestId("msg-assistant")).toHaveTextContent("Here's what I found."),
  );
});


test("toggles default on and the settings accordion collapses", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("settings-documents")).toBeInTheDocument());

  expect(screen.getByTestId("rag-toggle")).toBeChecked();
  expect(screen.getByTestId("memory-toggle")).toBeChecked();
  expect(screen.getByTestId("tools-toggle")).toBeChecked();
  expect(screen.getByTestId("approve-tools-toggle")).toBeChecked();
  // Three grouped lines.
  expect(screen.getByTestId("settings-tools")).toBeInTheDocument();
  expect(screen.getByTestId("settings-memory")).toBeInTheDocument();

  // Accordion collapses and re-expands.
  fireEvent.click(screen.getByTestId("settings-toggle"));
  await waitFor(() => expect(screen.queryByTestId("settings-documents")).toBeNull());
  fireEvent.click(screen.getByTestId("settings-toggle"));
  await waitFor(() => expect(screen.getByTestId("settings-documents")).toBeInTheDocument());
});


test("collapses and expands the panel sidebar", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("side-panel")).toBeInTheDocument());
  // Panel buttons live in the sidebar.
  expect(screen.getByTestId("memory-show")).toBeInTheDocument();

  // Collapse -> sidebar gone, chat takes full width.
  fireEvent.click(screen.getByTestId("side-toggle"));
  await waitFor(() => expect(screen.queryByTestId("side-panel")).not.toBeInTheDocument());

  // A re-open control remains; clicking it restores the sidebar.
  fireEvent.click(screen.getByTestId("side-toggle"));
  await waitFor(() => expect(screen.getByTestId("side-panel")).toBeInTheDocument());
});


test("opens a past conversation and loads its messages", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchConversations").mockResolvedValue([CONV]);
  vi.spyOn(api, "fetchConversation").mockResolvedValue({
    id: "c1",
    title: "Old chat",
    messages: [
      { role: "user", content: "earlier question" },
      { role: "assistant", content: "earlier answer" },
    ],
  });

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("open-c1")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("open-c1"));

  await waitFor(() => expect(screen.getByTestId("msg-user")).toHaveTextContent("earlier question"));
  expect(screen.getByTestId("msg-assistant")).toHaveTextContent("earlier answer");
});
