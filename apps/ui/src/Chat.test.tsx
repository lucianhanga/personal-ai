import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  // Upload lives in Settings > Documents (the default settings section).
  fireEvent.click(await screen.findByTestId("nav-settings"));
  await waitFor(() => expect(screen.getByTestId("file-input")).toBeInTheDocument());

  const file = new File(["hi"], "geo.txt", { type: "text/plain" });
  fireEvent.change(screen.getByTestId("file-input"), { target: { files: [file] } });

  await waitFor(() => expect(upload).toHaveBeenCalled());
  await waitFor(() => expect(screen.getByTestId("file-list")).toHaveTextContent("geo.txt"));
  // Back on the chat view, RAG was auto-enabled now that a document exists.
  fireEvent.click(screen.getByTestId("nav-chat"));
  expect(screen.getByTestId("rag-toggle")).toBeChecked();
});

test("defaults 'Use my documents' on when documents already exist", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchFiles").mockResolvedValue([DOC]);

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("rag-toggle")).toBeChecked());
  expect(screen.queryByTestId("rag-hint")).toBeNull();
  // The document is listed under Settings > Documents.
  fireEvent.click(screen.getByTestId("nav-settings"));
  await waitFor(() => expect(screen.getByTestId("file-list")).toHaveTextContent("geo.txt"));
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
      ...Array(8).fill(expect.any(Function)),
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
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "search rust" } });
  fireEvent.click(screen.getByTestId("send"));

  await waitFor(() =>
    expect(screen.getByTestId("msg-assistant")).toHaveTextContent("Here's what I found."),
  );
  // Tool calls live in a "Details" section, auto-opened while the latest answer streams.
  await waitFor(() => expect(screen.getByTestId("details-body")).toHaveTextContent("web_search"));
});


test("per-session toggles default on; the Chat/Settings tabs switch views", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("session-controls")).toBeInTheDocument());

  // Per-session toggles live in the strip above the composer and default on.
  expect(screen.getByTestId("rag-toggle")).toBeChecked();
  expect(screen.getByTestId("memory-toggle")).toBeChecked();
  expect(screen.getByTestId("tools-toggle")).toBeChecked();
  expect(screen.getByTestId("approve-tools-toggle")).toBeChecked();
  expect((screen.getByTestId("reasoning-select") as HTMLSelectElement).value).toBe("brief");

  // Switch to the Settings view: the section nav appears and the chat workspace is hidden.
  fireEvent.click(screen.getByTestId("nav-settings"));
  await waitFor(() => expect(screen.getByTestId("settings-view")).toBeInTheDocument());
  expect(screen.getByTestId("settings-nav")).toBeInTheDocument();
  expect(screen.queryByTestId("workspace")).toBeNull();

  // Back to Chat.
  fireEvent.click(screen.getByTestId("nav-chat"));
  await waitFor(() => expect(screen.getByTestId("workspace")).toBeInTheDocument());
});


test("renames a chat", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchConversations").mockResolvedValue([
    { id: "cA", title: "Old name", updated_at: "2026-06-09T00:00:00Z" },
  ]);
  const rename = vi.spyOn(api, "renameConversation").mockResolvedValue();

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("rename-cA")).toBeInTheDocument());

  fireEvent.click(screen.getByTestId("rename-cA"));
  const input = screen.getByTestId("rename-input-cA");
  fireEvent.change(input, { target: { value: "Renamed" } });
  fireEvent.keyDown(input, { key: "Enter" });

  await waitFor(() => expect(rename).toHaveBeenCalledWith("demo", "cA", "Renamed"));
  await waitFor(() => expect(screen.getByTestId("open-cA")).toHaveTextContent("Renamed"));
});


test("keeps a chat streaming (with an in-progress marker) when switching chats", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchConversations").mockResolvedValue([
    { id: "cA", title: "A", updated_at: "2026-06-09T00:00:00Z" },
    { id: "cB", title: "B", updated_at: "2026-06-09T00:00:00Z" },
  ]);
  vi.spyOn(api, "fetchConversation").mockImplementation(async (_t, id) => ({
    id,
    title: id,
    messages: [],
  }));
  let release: () => void = () => {};
  vi.spyOn(api, "streamChat").mockImplementation(async (_p, onDelta) => {
    onDelta("partial from A");
    await new Promise<void>((res) => {
      release = res;
    });
  });

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );
  await waitFor(() => expect(screen.getByTestId("open-cA")).toBeInTheDocument());

  // Start generating in chat A.
  fireEvent.click(screen.getByTestId("open-cA"));
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "hi A" } });
  fireEvent.click(screen.getByTestId("send"));
  await waitFor(() => expect(screen.getByTestId("busy-cA")).toBeInTheDocument());

  // Switch to chat B while A is still generating.
  fireEvent.click(screen.getByTestId("open-cB"));
  await waitFor(() => expect(screen.getByTestId("open-cB")).toBeInTheDocument());
  // A keeps its in-progress marker (not cancelled); B's view doesn't show A's partial output.
  expect(screen.getByTestId("busy-cA")).toBeInTheDocument();
  expect(screen.queryByText(/partial from A/)).toBeNull();

  // Complete A's stream; its marker clears.
  act(() => release());
  await waitFor(() => expect(screen.queryByTestId("busy-cA")).toBeNull());
});


test("the chosen reasoning amount is sent to the chat request", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  const stream = vi.spyOn(api, "streamChat").mockResolvedValue();

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );
  // Default is Brief (think on, bounded).
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "why?" } });
  fireEvent.click(screen.getByTestId("send"));
  await waitFor(() =>
    expect(stream).toHaveBeenCalledWith(
      expect.objectContaining({ reasoning: "brief", think: true }),
      ...Array(8).fill(expect.any(Function)),
    ),
  );

  // Switch to Off -> reasoning off, think false.
  fireEvent.change(screen.getByTestId("reasoning-select"), { target: { value: "off" } });
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "again" } });
  fireEvent.click(screen.getByTestId("send"));
  await waitFor(() =>
    expect(stream).toHaveBeenCalledWith(
      expect.objectContaining({ reasoning: "off", think: false }),
      ...Array(8).fill(expect.any(Function)),
    ),
  );
});


test("surfaces a backend stream error in the assistant bubble", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "streamChat").mockImplementation(
    async (_p, _onDelta, _onCit, _onTool, _onUsage, _onThink, onError) => {
      onError?.("egress not allowed for host: evil.example");
    },
  );

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "go" } });
  fireEvent.click(screen.getByTestId("send"));

  await waitFor(() =>
    expect(screen.getByTestId("msg-assistant")).toHaveTextContent("egress not allowed"),
  );
});


test("collapses and expands the chats column", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("chats-panel")).toBeInTheDocument());

  fireEvent.click(screen.getByTestId("chats-toggle"));
  await waitFor(() => expect(screen.queryByTestId("chats-panel")).not.toBeInTheDocument());

  fireEvent.click(screen.getByTestId("chats-toggle"));
  await waitFor(() => expect(screen.getByTestId("chats-panel")).toBeInTheDocument());
});


test("collapses and expands the panel sidebar", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("side-panel")).toBeInTheDocument());

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

test("durable human gate: shows approve/reject and resumes on approve", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  // The turn streams a draft answer then suspends at the human gate (approval_request).
  vi.spyOn(api, "streamChat").mockImplementation(
    async (_p, onDelta, _onCit, _onTool, _onUsage, _onThink, _onError, onApproval) => {
      onDelta("draft answer");
      onApproval?.({ run_id: "r1", answer: "draft answer", critique: "looks ok" });
    },
  );
  const resume = vi
    .spyOn(api, "resumeChat")
    .mockImplementation(async (_p, onDelta) => onDelta("final answer"));

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "hi" } });
  fireEvent.click(screen.getByTestId("send"));

  // The approve/reject affordance appears with the draft answer shown.
  await waitFor(() => expect(screen.getByTestId("approval-request")).toBeInTheDocument());
  expect(screen.getByText(/draft answer/)).toBeInTheDocument();

  // Approving resumes the run and replaces the bubble with the finalized answer.
  fireEvent.click(screen.getByTestId("approve"));
  await waitFor(() =>
    expect(resume).toHaveBeenCalledWith(
      expect.objectContaining({ runId: "r1", decision: "approve" }),
      ...Array(3).fill(expect.any(Function)),
    ),
  );
  await waitFor(() => expect(screen.getByText(/final answer/)).toBeInTheDocument());
  expect(screen.queryByTestId("approval-request")).not.toBeInTheDocument();
});

test("streams planner and critic steps into the live trace (followable agent flow)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "streamChat").mockImplementation(
    async (_p, onDelta, _c, _t, _u, _th, _e, _ap, onAgentStep) => {
      onAgentStep?.({ kind: "plan", text: "outline the answer" });
      onDelta("the answer");
      onAgentStep?.({ kind: "critique", text: "looks complete" });
    },
  );

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "hi" } });
  fireEvent.click(screen.getByTestId("send"));

  await waitFor(() => expect(screen.getByTestId("msg-assistant")).toHaveTextContent("the answer"));
  // The per-message Details auto-opens while the turn runs, so the agent steps are visible inline,
  // in order, without any extra click.
  await waitFor(() => expect(screen.getByTestId("details-plan")).toHaveTextContent("Planner"));
  expect(screen.getByTestId("details-plan")).toHaveTextContent("outline the answer");
  expect(screen.getByTestId("details-critique")).toHaveTextContent("Critic");
  expect(screen.getByTestId("details-critique")).toHaveTextContent("looks complete");
});
