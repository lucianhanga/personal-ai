import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { Chat, formatDuration, micErrorMessage, transcribeErrorMessage } from "./Chat";
import * as api from "./api";

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

const DRAFT_KEY = "personalai_composer_draft";

// #424: transcribe/describe now return {text|description, model, ms}. Helpers keep the existing
// string-centric tests terse while satisfying the enriched return types.
const tr = (text: string): api.TranscribeResult => ({ text, model: "whisper-1", ms: 100 });
const dsc = (description: string): api.DescribeResult => ({ description, model: "vision:7b", ms: 100 });

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

test("restores an unsent composer draft (text + attachment) from sessionStorage (#369)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  // Simulate the draft a previous mount left behind before <Chat> was unmounted by a re-validation.
  sessionStorage.setItem(
    DRAFT_KEY,
    JSON.stringify({
      input: "half-written question",
      images: [{ id: "i1", src: "data:image/png;base64,AAAA", description: "a cat" }],
    }),
  );
  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("composer") as HTMLTextAreaElement).value).toBe(
      "half-written question",
    ),
  );
  // The staged (described) image is back too, not silently dropped.
  expect(screen.getByTestId("image-attachments").querySelectorAll("img")).toHaveLength(1);
});

test("persists the composer draft to sessionStorage so a remount keeps it (#369)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  render(<Chat token="demo" />);
  const composer = await screen.findByTestId("composer");
  fireEvent.change(composer, { target: { value: "remember me" } });
  await waitFor(() => {
    const raw = sessionStorage.getItem(DRAFT_KEY);
    expect(raw && (JSON.parse(raw) as { input: string }).input).toBe("remember me");
  });
});

test("switching provider reloads its models", async () => {
  mockProviders();
  const fetchModels = vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("provider-select")).toBeInTheDocument());

  fireEvent.change(screen.getByTestId("provider-select"), { target: { value: "openai" } });
  await waitFor(() => expect(fetchModels).toHaveBeenCalledWith("demo", "openai"));
});

test("records voice and inserts the transcript into the composer (M9.2)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchTranscribeEnabled").mockResolvedValue(true);
  vi.spyOn(api, "transcribeAudio").mockResolvedValue(tr("hello from my voice"));

  // Mock the browser media APIs (not in jsdom).
  const track = { stop: vi.fn() };
  vi.stubGlobal("navigator", {
    ...navigator,
    mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [track] }) },
  });
  let onstop: (() => void) | null = null;
  class FakeRecorder {
    ondataavailable: ((e: { data: Blob }) => void) | null = null;
    set onstop(fn: () => void) {
      onstop = fn;
    }
    start(): void {
      this.ondataavailable?.({ data: new Blob(["x"], { type: "audio/webm" }) });
    }
    stop(): void {
      onstop?.();
    }
  }
  vi.stubGlobal("MediaRecorder", FakeRecorder as unknown as typeof MediaRecorder);

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mic")).toBeInTheDocument());

  fireEvent.click(screen.getByTestId("mic")); // start
  await waitFor(() =>
    expect(screen.getByTestId("mic")).toHaveAttribute("aria-label", "Stop recording"),
  );
  fireEvent.click(screen.getByTestId("mic")); // stop -> transcribe

  await waitFor(() =>
    expect((screen.getByTestId("composer") as HTMLTextAreaElement).value).toContain(
      "hello from my voice",
    ),
  );
  // After transcription, the grace-period auto-send banner shows (M9.2c).
  await waitFor(() => expect(screen.getByTestId("autosend-banner")).toBeInTheDocument());
});

test("editing the transcript cancels the auto-send", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchTranscribeEnabled").mockResolvedValue(true);
  vi.spyOn(api, "transcribeAudio").mockResolvedValue(tr("draft text"));
  const track = { stop: vi.fn() };
  vi.stubGlobal("navigator", {
    ...navigator,
    mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [track] }) },
  });
  let onstop: (() => void) | null = null;
  class FakeRecorder {
    ondataavailable: ((e: { data: Blob }) => void) | null = null;
    set onstop(fn: () => void) {
      onstop = fn;
    }
    start(): void {
      this.ondataavailable?.({ data: new Blob(["x"], { type: "audio/webm" }) });
    }
    stop(): void {
      onstop?.();
    }
  }
  vi.stubGlobal("MediaRecorder", FakeRecorder as unknown as typeof MediaRecorder);

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mic")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("mic"));
  await waitFor(() =>
    expect(screen.getByTestId("mic")).toHaveAttribute("aria-label", "Stop recording"),
  );
  fireEvent.click(screen.getByTestId("mic"));
  await waitFor(() => expect(screen.getByTestId("autosend-banner")).toBeInTheDocument());

  // The countdown shows a 3-2-1 figure, and pressing Stop cancels the auto-send so the user can edit.
  expect(screen.getByTestId("autosend-count")).toHaveTextContent("3");
  fireEvent.click(screen.getByTestId("autosend-cancel"));
  expect(screen.queryByTestId("autosend-banner")).toBeNull();
  // The transcript stays in the composer, editable, and is not sent.
  expect((screen.getByTestId("composer") as HTMLTextAreaElement).value).toContain("draft text");

  // Editing the composer also cancels a pending auto-send.
  fireEvent.click(screen.getByTestId("mic"));
  await waitFor(() =>
    expect(screen.getByTestId("mic")).toHaveAttribute("aria-label", "Stop recording"),
  );
  fireEvent.click(screen.getByTestId("mic"));
  await waitFor(() => expect(screen.getByTestId("autosend-banner")).toBeInTheDocument());
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "draft text edited" } });
  expect(screen.queryByTestId("autosend-banner")).toBeNull();
});

test("auto-sends the transcript after the grace period if untouched (M9.2c)", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchTranscribeEnabled").mockResolvedValue(true);
  vi.spyOn(api, "transcribeAudio").mockResolvedValue(tr("auto sent text"));
  const stream = vi.spyOn(api, "streamChat").mockImplementation(async (_p, onDelta) => {
    onDelta("ok");
  });
  const track = { stop: vi.fn() };
  vi.stubGlobal("navigator", {
    ...navigator,
    mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [track] }) },
  });
  let onstop: (() => void) | null = null;
  class FakeRecorder {
    ondataavailable: ((e: { data: Blob }) => void) | null = null;
    set onstop(fn: () => void) {
      onstop = fn;
    }
    start(): void {
      this.ondataavailable?.({ data: new Blob(["x"], { type: "audio/webm" }) });
    }
    stop(): void {
      onstop?.();
    }
  }
  vi.stubGlobal("MediaRecorder", FakeRecorder as unknown as typeof MediaRecorder);

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mic")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("mic"));
  await waitFor(() =>
    expect(screen.getByTestId("mic")).toHaveAttribute("aria-label", "Stop recording"),
  );
  fireEvent.click(screen.getByTestId("mic"));
  await waitFor(() => expect(screen.getByTestId("autosend-banner")).toBeInTheDocument());

  // Let the 3-second countdown elapse without touching the text.
  await act(async () => {
    vi.advanceTimersByTime(3100);
  });
  await waitFor(() => expect(stream).toHaveBeenCalled());
  expect(stream.mock.calls[0][0].messages.at(-1)?.content).toContain("auto sent text");
  // The countdown must fire the send exactly once — a double-fire would create a duplicate
  // (empty) conversation. Let any extra timer ticks run to be sure no second send sneaks in.
  await act(async () => {
    vi.advanceTimersByTime(3000);
  });
  expect(stream).toHaveBeenCalledTimes(1);
  vi.useRealTimers();
});

test("STT message helpers map failures to plain language (M9.2f)", () => {
  expect(micErrorMessage({ name: "NotAllowedError" })).toMatch(/blocked/i);
  expect(micErrorMessage({ name: "NotFoundError" })).toMatch(/no microphone/i);
  expect(micErrorMessage(new Error("boom"))).toMatch(/unavailable/i);
  expect(transcribeErrorMessage("transcribe failed: 413")).toMatch(/too long/i);
  expect(transcribeErrorMessage("transcribe failed: 500")).toMatch(/failed/i);
  expect(formatDuration(0)).toBe("0:00");
  expect(formatDuration(9)).toBe("0:09");
  expect(formatDuration(75)).toBe("1:15");
});

test("shows a no-speech notice when the transcript is empty (M9.2f)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchTranscribeEnabled").mockResolvedValue(true);
  vi.spyOn(api, "transcribeAudio").mockResolvedValue(tr("")); // VAD strips silence -> empty
  const track = { stop: vi.fn() };
  vi.stubGlobal("navigator", {
    ...navigator,
    mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [track] }) },
  });
  let onstop: (() => void) | null = null;
  class FakeRecorder {
    ondataavailable: ((e: { data: Blob }) => void) | null = null;
    set onstop(fn: () => void) {
      onstop = fn;
    }
    start(): void {
      this.ondataavailable?.({ data: new Blob(["x"], { type: "audio/webm" }) });
    }
    stop(): void {
      onstop?.();
    }
  }
  vi.stubGlobal("MediaRecorder", FakeRecorder as unknown as typeof MediaRecorder);

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mic")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("mic"));
  await waitFor(() =>
    expect(screen.getByTestId("mic")).toHaveAttribute("aria-label", "Stop recording"),
  );
  fireEvent.click(screen.getByTestId("mic"));
  await waitFor(() =>
    expect(screen.getByTestId("mic-notice")).toHaveTextContent(/no speech detected/i),
  );
  // No transcript -> no auto-send banner.
  expect(screen.queryByTestId("autosend-banner")).toBeNull();
});

test("shows a friendly error when mic permission is denied (M9.2f)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchTranscribeEnabled").mockResolvedValue(true);
  vi.stubGlobal("navigator", {
    ...navigator,
    mediaDevices: {
      getUserMedia: vi.fn().mockRejectedValue(
        Object.assign(new Error("denied"), { name: "NotAllowedError" }),
      ),
    },
  });

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("mic")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("mic"));
  await waitFor(() =>
    expect(screen.getByTestId("chat-error")).toHaveTextContent(/microphone access was blocked/i),
  );
});

// Drop an audio file onto the composer dropzone (drag-drop is the only way to add audio now, #406).
function dropAudio(file: File): void {
  fireEvent.drop(screen.getByTestId("composer-dropzone"), {
    dataTransfer: { files: [file], types: ["Files"] },
  });
}

test("dropping an audio file creates a transcribing chip that becomes done with a snippet (#406)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchTranscribeEnabled").mockResolvedValue(true);
  // Defer resolution so the transcribing state is observable, then resolve.
  let resolve!: (result: api.TranscribeResult) => void;
  const transcribe = vi
    .spyOn(api, "transcribeAudio")
    .mockReturnValue(new Promise<api.TranscribeResult>((r) => (resolve = r)));

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("composer-dropzone")).toBeInTheDocument());

  const file = new File(["x"], "meeting.mp3", { type: "audio/mpeg" });
  dropAudio(file);

  // A chip appears in the transcribing state.
  await waitFor(() => {
    const chip = screen.getByTestId("audio-attachment");
    expect(chip).toHaveAttribute("data-status", "transcribing");
    expect(chip).toHaveTextContent(/meeting\.mp3/);
    expect(chip).toHaveTextContent(/transcribing/i);
  });
  // The filename + an AbortSignal are forwarded to the backend.
  expect(transcribe).toHaveBeenCalledWith("demo", file, "meeting.mp3", expect.any(AbortSignal));

  await act(async () => {
    resolve(tr("the full transcript of the meeting recording goes on for a while"));
  });

  // The chip becomes done with a one-line snippet of the transcript; no auto-send banner.
  await waitFor(() =>
    expect(screen.getByTestId("audio-attachment")).toHaveAttribute("data-status", "done"),
  );
  expect(screen.getByTestId("audio-attachment")).toHaveTextContent(/the full transcript/i);
  expect(screen.queryByTestId("autosend-banner")).toBeNull();
});

test("an empty audio transcript yields a no-speech chip (#406)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchTranscribeEnabled").mockResolvedValue(true);
  vi.spyOn(api, "transcribeAudio").mockResolvedValue(tr(""));

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("composer-dropzone")).toBeInTheDocument());

  dropAudio(new File(["x"], "silent.wav", { type: "audio/wav" }));

  await waitFor(() => {
    const chip = screen.getByTestId("audio-attachment");
    expect(chip).toHaveAttribute("data-status", "empty");
    expect(chip).toHaveTextContent(/no speech/i);
  });
});

test("a done audio chip opens a transcript panel on focus with a Copy button (#406)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchTranscribeEnabled").mockResolvedValue(true);
  vi.spyOn(api, "transcribeAudio").mockResolvedValue(tr("hello transcript world"));

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("composer-dropzone")).toBeInTheDocument());

  dropAudio(new File(["x"], "talk.mp3", { type: "audio/mpeg" }));
  await waitFor(() =>
    expect(screen.getByTestId("audio-attachment")).toHaveAttribute("data-status", "done"),
  );

  // Panel is closed until the chip is focused.
  expect(screen.queryByTestId("audio-panel")).toBeNull();
  fireEvent.focus(screen.getByTestId("audio-attachment"));

  const panel = await screen.findByTestId("audio-panel");
  expect(panel).toHaveTextContent("hello transcript world");
  // Copy control is present and labeled (icon button, not the word "Copy").
  const copy = panel.querySelector("[data-testid^='copy-audio-']");
  expect(copy).not.toBeNull();
  expect(copy).toHaveAttribute("aria-label", "Copy transcript");
});

test("the transcript panel STAYS open when the mouse leaves the chip (#410)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchTranscribeEnabled").mockResolvedValue(true);
  vi.spyOn(api, "transcribeAudio").mockResolvedValue(tr("reach the copy button"));

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("composer-dropzone")).toBeInTheDocument());

  dropAudio(new File(["x"], "talk.mp3", { type: "audio/mpeg" }));
  await waitFor(() =>
    expect(screen.getByTestId("audio-attachment")).toHaveAttribute("data-status", "done"),
  );

  const chip = screen.getByTestId("audio-attachment");
  // Open via click (also exercises the click-to-toggle affordance).
  fireEvent.click(chip);
  expect(await screen.findByTestId("audio-panel")).toBeInTheDocument();

  // The core #410 bug: moving the pointer off the chip must NOT dismiss the panel,
  // otherwise the user can never travel into the panel to click Copy.
  fireEvent.mouseLeave(chip);
  expect(screen.getByTestId("audio-panel")).toBeInTheDocument();

  // The Copy control copies the full transcript and stays reachable.
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  const copy = screen.getByRole("button", { name: "Copy transcript" });
  fireEvent.click(copy);
  expect(writeText).toHaveBeenCalledWith("reach the copy button");
});

test("removing an audio chip drops it from the row (#406)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchTranscribeEnabled").mockResolvedValue(true);
  vi.spyOn(api, "transcribeAudio").mockResolvedValue(tr("some words"));

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("composer-dropzone")).toBeInTheDocument());

  dropAudio(new File(["x"], "clip.mp3", { type: "audio/mpeg" }));
  await waitFor(() =>
    expect(screen.getByTestId("audio-attachment")).toHaveAttribute("data-status", "done"),
  );

  const remove = screen.getByRole("button", { name: /remove clip\.mp3/i });
  fireEvent.click(remove);
  await waitFor(() => expect(screen.queryByTestId("audio-attachment")).toBeNull());
});

test("sending folds the audio transcript into the message content as a labeled block (#406)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchTranscribeEnabled").mockResolvedValue(true);
  vi.spyOn(api, "transcribeAudio").mockResolvedValue(tr("the spoken words"));
  const stream = vi.spyOn(api, "streamChat").mockImplementation(async (_p, onDelta) => {
    onDelta("ok");
  });

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );

  dropAudio(new File(["x"], "memo.mp3", { type: "audio/mpeg" }));
  await waitFor(() =>
    expect(screen.getByTestId("audio-attachment")).toHaveAttribute("data-status", "done"),
  );

  fireEvent.change(screen.getByTestId("composer"), { target: { value: "please review" } });
  fireEvent.click(screen.getByTestId("send"));

  await waitFor(() => expect(stream).toHaveBeenCalled());
  const sent = stream.mock.calls[0][0].messages;
  const last = sent[sent.length - 1];
  expect(last.role).toBe("user");
  expect(last.content).toBe("please review\n\n[Audio: memo.mp3]\nthe spoken words");
  // Display-vs-model split (#426): the bubble gets the original prompt; the model gets the fold above.
  expect(last.displayContent).toBe("please review");
  // The COMPOSER chip row clears after a successful send (the sent message now renders its own
  // read-only transcript chip with data-status="sent", so we scope to the composer's `done` chip).
  await waitFor(() =>
    expect(document.querySelector('[data-testid="audio-attachment"][data-status="done"]')).toBeNull(),
  );
});

test("the old file-picker and Summarize affordances are gone (#406)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchTranscribeEnabled").mockResolvedValue(true);

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("composer-dropzone")).toBeInTheDocument());

  expect(screen.queryByTestId("audio-file-btn")).toBeNull();
  expect(screen.queryByTestId("audio-file-input")).toBeNull();
  // Summarize never appears, even with composer text.
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "anything" } });
  expect(screen.queryByTestId("summarize-send")).toBeNull();
});

test("attaches an image, describes it eagerly, and sends it (vision) (#419)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  const describe = vi.spyOn(api, "describeImage").mockResolvedValue(dsc("a tabby cat on a sofa"));
  const stream = vi.spyOn(api, "streamChat").mockImplementation(async (_p, onDelta) => {
    onDelta("I see a cat.");
  });

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );

  // Drag-drop a fake PNG onto the composer; it's downscaled (no-op here) + described in the bg.
  const file = new File(["x"], "cat.png", { type: "image/png" });
  fireEvent.drop(screen.getByTestId("composer-dropzone"), {
    dataTransfer: { files: [file], types: ["Files"] },
  });
  // Chip appears, then becomes `done` once the eager description resolves.
  await waitFor(() => expect(describe).toHaveBeenCalled());
  await waitFor(() =>
    expect(screen.getByTestId("image-attachment")).toHaveAttribute("data-status", "done"),
  );

  fireEvent.change(screen.getByTestId("composer"), { target: { value: "what is this?" } });
  fireEvent.click(screen.getByTestId("send"));

  // The user message + its image render, and the streamed request carried the image.
  await waitFor(() => expect(screen.getByTestId("msg-images")).toBeInTheDocument());
  await waitFor(() => {
    const sent = stream.mock.calls[0][0].messages;
    const lastUser = sent[sent.length - 1];
    expect(lastUser.images?.[0]).toMatch(/^data:image\//);
    // Vision model: the image is sent; the description is NOT folded into the content.
    expect(lastUser.content).not.toContain("[Image:");
    expect(lastUser.image_descriptions?.[0]).toBe("a tabby cat on a sofa");
  });
  // The attachment tray clears after sending.
  expect(screen.queryByTestId("image-attachments")).toBeNull();
});

test("an uploaded image yields a live activity that persists in the send body (#424)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "describeImage").mockResolvedValue(dsc("a tabby cat on a sofa"));
  const stream = vi.spyOn(api, "streamChat").mockImplementation(async (_p, onDelta) => {
    onDelta("I see a cat.");
  });

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );

  const file = new File(["x"], "cat.png", { type: "image/png" });
  fireEvent.drop(screen.getByTestId("composer-dropzone"), {
    dataTransfer: { files: [file], types: ["Files"] },
  });

  // While the chip is `done` pre-submit, the Activity panel shows a live "Preparing your message"
  // cluster with a resource node for the image (the live -> persisted mirror, #424).
  await waitFor(() => expect(screen.getByTestId("timeline-preturn")).toBeInTheDocument());
  const liveNode = screen.getByTestId("timeline-resource");
  expect(liveNode).toHaveTextContent("Described image — cat.png");

  fireEvent.change(screen.getByTestId("composer"), { target: { value: "what is this?" } });
  fireEvent.click(screen.getByTestId("send"));

  // The submitted user turn carries the sanitized-shape activity in its `activities` field.
  await waitFor(() => {
    const sent = stream.mock.calls[0][0].messages;
    const lastUser = sent[sent.length - 1];
    expect(lastUser.activities).toHaveLength(1);
    const act = lastUser.activities![0];
    expect(act.kind).toBe("resource");
    expect(act.action).toBe("image_described");
    expect(act.ref).toBe("cat.png");
    expect(act.model).toBe("vision:7b");
    expect(act.ms).toBe(100);
  });
  // On submit the pre-turn cluster vanishes (the committed turn becomes the source of truth).
  await waitFor(() => expect(screen.queryByTestId("timeline-preturn")).toBeNull());
});

test("non-vision model folds the image description into the message content (#419)", async () => {
  // A non-vision default model can't see the image, so its description is folded as text.
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue({
    defaultModel: "textonly",
    models: [
      {
        name: "textonly",
        local: true,
        capabilities: {
          text: true,
          vision: false,
          embeddings: false,
          tool_calling: false,
          structured_output: false,
          thinking: false,
          max_context_tokens: 8192,
        },
      },
    ],
  });
  vi.spyOn(api, "describeImage").mockResolvedValue(dsc("a tabby cat on a sofa"));
  const stream = vi.spyOn(api, "streamChat").mockImplementation(async (_p, onDelta) => {
    onDelta("ok");
  });
  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("textonly"),
  );
  const file = new File(["x"], "cat.png", { type: "image/png" });
  fireEvent.drop(screen.getByTestId("composer-dropzone"), {
    dataTransfer: { files: [file], types: ["Files"] },
  });
  await waitFor(() =>
    expect(screen.getByTestId("image-attachment")).toHaveAttribute("data-status", "done"),
  );
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "what is this?" } });
  fireEvent.click(screen.getByTestId("send"));
  await waitFor(() => {
    const sent = stream.mock.calls[0][0].messages;
    expect(sent[sent.length - 1].content).toContain("[Image: a tabby cat on a sofa]");
  });
});

test("removing an image chip aborts its in-flight description (#419)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  // Never-resolving describe so the chip stays `describing` and the abort is observable.
  let abortSignal: AbortSignal | undefined;
  vi.spyOn(api, "describeImage").mockImplementation((_t, _b, signal) => {
    abortSignal = signal;
    return new Promise<api.DescribeResult>(() => {});
  });
  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("composer-dropzone")).toBeInTheDocument());
  const file = new File(["x"], "cat.png", { type: "image/png" });
  fireEvent.drop(screen.getByTestId("composer-dropzone"), {
    dataTransfer: { files: [file], types: ["Files"] },
  });
  await waitFor(() => expect(screen.getByTestId("image-attachment")).toBeInTheDocument());
  const remove = screen.getByTestId("image-attachments").querySelector("button");
  fireEvent.click(remove!);
  expect(screen.queryByTestId("image-attachments")).toBeNull();
  expect(abortSignal?.aborted).toBe(true);
});

// --- document attachments (Phase 1 inline-fold tier, #416/#420) ---------------------------------

// Drop a document file onto the composer dropzone (drag-drop, like audio/images).
function dropDoc(file: File): void {
  fireEvent.drop(screen.getByTestId("composer-dropzone"), {
    dataTransfer: { files: [file], types: ["Files"] },
  });
}

test("dropping a small document extracts it and folds the text into the message (#416)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "extractDocument").mockResolvedValue({
    name: "notes.txt",
    mime: "text/plain",
    text: "the quick brown fox",
    truncated: false,
  });
  const stream = vi.spyOn(api, "streamChat").mockImplementation(async (_p, onDelta) => {
    onDelta("ok");
  });

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );

  dropDoc(new File(["the quick brown fox"], "notes.txt", { type: "text/plain" }));

  // The chip lands in the `small` state (under the inline token gate).
  await waitFor(() =>
    expect(screen.getByTestId("document-attachment")).toHaveAttribute("data-status", "small"),
  );

  // A small doc carries the neutral "In message" affordance (folded inline, not RAG-indexed).
  expect(screen.getByTestId("document-retrieval-badge")).toHaveAttribute("data-retrieval", "inline");
  expect(screen.getByTestId("document-retrieval-badge")).toHaveTextContent(/in message/i);

  fireEvent.change(screen.getByTestId("composer"), { target: { value: "summarize this" } });
  fireEvent.click(screen.getByTestId("send"));

  await waitFor(() => expect(stream).toHaveBeenCalled());
  const sent = stream.mock.calls[0][0].messages;
  const last = sent[sent.length - 1];
  expect(last.content).toBe("summarize this\n\n[Document: notes.txt]\nthe quick brown fox");
  // Display-vs-model split (#426): the original prompt (not the folded content) is sent for the
  // bubble; the model still receives the folded `content` asserted above.
  expect(last.displayContent).toBe("summarize this");
  // Ingest-at-send (#436): a small doc is folded inline and is NOT placed in `documents_full`.
  expect(last.documents_full).toBeUndefined();
  // The COMPOSER chip row clears after a successful send (the sent message now renders its own
  // read-only transcript chip with data-status="sent", so we scope to the composer's `small` chip).
  await waitFor(() =>
    expect(document.querySelector('[data-testid="document-attachment"][data-status="small"]')).toBeNull(),
  );
});

test("a large document is sent in documents_full for RAG ingest, not folded inline (#436)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  // Over the 6000-token inline gate (~4 chars/token -> > 24000 chars).
  const big = "lorem ipsum ".repeat(3000);
  vi.spyOn(api, "extractDocument").mockResolvedValue({
    name: "report.pdf",
    mime: "application/pdf",
    text: big,
    truncated: false,
  });
  // Eager ingest-at-attach (#420): persistence on + a conversation create + the ingest call all
  // succeed, so the large doc reaches the truthful "indexed" badge.
  vi.spyOn(api, "fetchConversations").mockResolvedValue([]);
  vi.spyOn(api, "createConversation").mockResolvedValue({
    id: "c1",
    title: "report.pdf",
    updated_at: "2026-06-07T00:00:00Z",
  });
  const ingest = vi
    .spyOn(api, "ingestConversationDocument")
    .mockResolvedValue({ document_id: "d1", chunk_count: 5, already_indexed: false });
  const stream = vi.spyOn(api, "streamChat").mockImplementation(async (_p, onDelta) => {
    onDelta("ok");
  });

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );

  dropDoc(new File(["x"], "report.pdf", { type: "application/pdf" }));
  await waitFor(() =>
    expect(screen.getByTestId("document-attachment")).toHaveAttribute("data-status", "large"),
  );
  // A large doc carries the amber "Searched in this chat" affordance (RAG-indexed, not inline). The
  // label is truthful to eager ingest (#420): it lands on "Searched in this chat" once ingest done.
  expect(screen.getByTestId("document-retrieval-badge")).toHaveAttribute("data-retrieval", "rag");
  await waitFor(() =>
    expect(screen.getByTestId("document-retrieval-badge")).toHaveTextContent(/searched in this chat/i),
  );
  expect(ingest).toHaveBeenCalledWith("demo", "c1", "report.pdf", big);

  // The full text is still reachable for read/copy via the panel.
  fireEvent.focus(screen.getByTestId("document-attachment"));
  expect(await screen.findByTestId("document-panel")).toHaveTextContent("lorem ipsum");

  // A large doc does not block sending; its text is NOT folded inline.
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "what is this?" } });
  fireEvent.click(screen.getByTestId("send"));
  await waitFor(() => expect(stream).toHaveBeenCalled());
  const last = stream.mock.calls[0][0].messages.at(-1);
  expect(last?.content).toBe("what is this?");
  expect(last?.content).not.toContain("[Document:");
  // Ingest-at-send (#436): the FULL extracted text goes in `documents_full` for conversation RAG.
  expect(last?.documents_full).toEqual([{ name: "report.pdf", text: big }]);
  // It also keeps a display chip in `documents` (drives the transcript chip on reload).
  expect(last?.documents).toEqual([{ name: "report.pdf", text: big }]);
});

test("a dropped document yields a `document_extracted` activity persisted in the send body (#424)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "extractDocument").mockResolvedValue({
    name: "notes.txt",
    mime: "text/plain",
    text: "the quick brown fox",
    truncated: false,
    model: null,
    ms: 42,
  });
  const stream = vi.spyOn(api, "streamChat").mockImplementation(async (_p, onDelta) => {
    onDelta("ok");
  });

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );
  dropDoc(new File(["x"], "notes.txt", { type: "text/plain" }));
  await waitFor(() =>
    expect(screen.getByTestId("document-attachment")).toHaveAttribute("data-status", "small"),
  );
  // A live pre-turn resource node for the document parse (no model -> document_extracted).
  await waitFor(() => expect(screen.getByTestId("timeline-preturn")).toBeInTheDocument());
  expect(screen.getByTestId("timeline-resource")).toHaveTextContent("Extracted document — notes.txt");

  fireEvent.change(screen.getByTestId("composer"), { target: { value: "summarize" } });
  fireEvent.click(screen.getByTestId("send"));
  await waitFor(() => {
    const lastUser = stream.mock.calls[0][0].messages.at(-1);
    expect(lastUser?.activities).toHaveLength(1);
    const act = lastUser!.activities![0];
    expect(act.action).toBe("document_extracted");
    expect(act.ref).toBe("notes.txt");
    expect(act.model).toBeNull(); // a local CPU parse has no model
    expect(act.ms).toBe(42);
  });
});

test("a dropped audio file yields an `audio_transcribed` activity persisted in the send body (#424)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchTranscribeEnabled").mockResolvedValue(true);
  vi.spyOn(api, "transcribeAudio").mockResolvedValue({
    text: "the meeting transcript",
    model: "whisper-1",
    ms: 1200,
  });
  const stream = vi.spyOn(api, "streamChat").mockImplementation(async (_p, onDelta) => {
    onDelta("ok");
  });

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("composer-dropzone")).toBeInTheDocument());
  fireEvent.drop(screen.getByTestId("composer-dropzone"), {
    dataTransfer: { files: [new File(["x"], "call.mp3", { type: "audio/mpeg" })], types: ["Files"] },
  });
  await waitFor(() =>
    expect(screen.getByTestId("audio-attachment")).toHaveAttribute("data-status", "done"),
  );
  await waitFor(() => expect(screen.getByTestId("timeline-preturn")).toBeInTheDocument());
  expect(screen.getByTestId("timeline-resource")).toHaveTextContent("Transcribed audio — call.mp3");

  fireEvent.change(screen.getByTestId("composer"), { target: { value: "what was said?" } });
  fireEvent.click(screen.getByTestId("send"));
  await waitFor(() => {
    const lastUser = stream.mock.calls[0][0].messages.at(-1);
    expect(lastUser?.activities).toHaveLength(1);
    const act = lastUser!.activities![0];
    expect(act.action).toBe("audio_transcribed");
    expect(act.ref).toBe("call.mp3");
    expect(act.model).toBe("whisper-1");
    expect(act.ms).toBe(1200);
  });
  // The folded content carries the transcript block (Option (b), #406).
  const lastContent = stream.mock.calls[0][0].messages.at(-1)?.content;
  expect(lastContent).toContain("[Audio: call.mp3]");
  expect(lastContent).toContain("the meeting transcript");
});

test("an unsupported / failed extraction yields an error chip (#416)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  // A recognized document extension that the backend rejects (e.g. an encrypted/corrupt PDF).
  vi.spyOn(api, "extractDocument").mockRejectedValue(new Error("unsupported file type"));

  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("composer-dropzone")).toBeInTheDocument());

  dropDoc(new File(["x"], "broken.pdf", { type: "application/pdf" }));
  await waitFor(() =>
    expect(screen.getByTestId("document-attachment")).toHaveAttribute("data-status", "error"),
  );
  expect(screen.getByTestId("document-attachment")).toHaveTextContent(/unsupported/i);
});

test("a scanned/image-only PDF (empty extracted text) becomes an `empty` chip, not folded or RAG'd (#446)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  // pypdf returns no text layer for a scanned PDF -> whitespace-only extraction. NOT an error.
  vi.spyOn(api, "extractDocument").mockResolvedValue({
    name: "scanned.pdf",
    mime: "application/pdf",
    text: "   \n  \t  ",
    truncated: false,
  });
  const stream = vi.spyOn(api, "streamChat").mockImplementation(async (_p, onDelta) => {
    onDelta("ok");
  });

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );

  dropDoc(new File(["x"], "scanned.pdf", { type: "application/pdf" }));

  // The chip lands in the `empty` state with the "no text found" cue (mirrors AudioChips' "no speech").
  await waitFor(() =>
    expect(screen.getByTestId("document-attachment")).toHaveAttribute("data-status", "empty"),
  );
  expect(screen.getByTestId("document-attachment")).toHaveTextContent(/no text found/i);
  // An empty doc is neither folded inline nor RAG-ingested -> no retrieval badge.
  expect(screen.queryByTestId("document-retrieval-badge")).toBeNull();

  // The panel opens and EXPLAINS the scanned/image-only case rather than showing a blank panel.
  fireEvent.focus(screen.getByTestId("document-attachment"));
  expect(await screen.findByTestId("document-empty-explanation")).toHaveTextContent(
    /scanned or image-only/i,
  );
  fireEvent.keyDown(document, { key: "Escape" });

  // With ONLY an empty doc attached (no typed text), Send stays blocked — nothing to send.
  expect(screen.getByTestId("send")).toBeDisabled();

  // With typed text, the message sends but the empty doc is excluded from the model-facing content,
  // from `documents` (the display chip), and from `documents_full` (RAG ingest).
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "summarize this" } });
  fireEvent.click(screen.getByTestId("send"));
  await waitFor(() => expect(stream).toHaveBeenCalled());
  const last = stream.mock.calls[0][0].messages.at(-1);
  expect(last?.content).toBe("summarize this"); // no "[Document: scanned.pdf]" fold
  expect(last?.content).not.toContain("[Document:");
  expect(last?.documents).toBeUndefined();
  expect(last?.documents_full).toBeUndefined();
});

test("the send button is blocked while a document is still extracting (#416)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  // Never-resolving extract so the chip stays `extracting`.
  vi.spyOn(api, "extractDocument").mockReturnValue(new Promise(() => {}));

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );

  dropDoc(new File(["x"], "slow.txt", { type: "text/plain" }));
  await waitFor(() =>
    expect(screen.getByTestId("document-attachment")).toHaveAttribute("data-status", "extracting"),
  );

  fireEvent.change(screen.getByTestId("composer"), { target: { value: "ready?" } });
  // Send is disabled until extraction settles, so the message cannot leave with a pending doc.
  expect(screen.getByTestId("send")).toBeDisabled();
});

test("removing a document chip aborts its in-flight extraction (#416)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  let abortSignal: AbortSignal | undefined;
  vi.spyOn(api, "extractDocument").mockImplementation((_t, _f, signal) => {
    abortSignal = signal;
    return new Promise(() => {});
  });
  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("composer-dropzone")).toBeInTheDocument());

  dropDoc(new File(["x"], "slow.txt", { type: "text/plain" }));
  await waitFor(() => expect(screen.getByTestId("document-attachment")).toBeInTheDocument());
  const remove = screen.getByTestId("document-attachments").querySelector("button");
  fireEvent.click(remove!);
  expect(screen.queryByTestId("document-attachments")).toBeNull();
  expect(abortSignal?.aborted).toBe(true);
});

test("shows a drag-and-drop hint and no Image button (#324)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  render(<Chat token="demo" />);
  await waitFor(() => expect(screen.getByTestId("composer-dropzone")).toBeInTheDocument());
  // The drag-drop hint is visible; the old upload button is gone.
  expect(screen.getByTestId("composer-dropzone")).toHaveTextContent(/drag .* drop images/i);
  expect(screen.queryByTestId("attach-image")).toBeNull();
  expect(screen.queryByTestId("image-input")).toBeNull();
  // Dragging files over the composer shows the drop overlay.
  fireEvent.dragOver(screen.getByTestId("composer-dropzone"), {
    dataTransfer: { types: ["Files"] },
  });
  expect(screen.getByTestId("drop-overlay")).toBeInTheDocument();
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

test("offers to allow an egress-blocked host inline in the reasoning pane", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "streamChat").mockImplementation(async (_p, onDelta, _c, onToolStep) => {
    // http_fetch's egress error format (the one the user hit).
    onToolStep?.({
      phase: "result",
      tool: "http_fetch",
      ok: false,
      error: "egress not allowed for host: api.open-meteo.com",
    });
    onDelta("I couldn't reach the weather API.");
  });
  const allow = vi.spyOn(api, "allowEgressHost").mockResolvedValue();

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "weather?" } });
  fireEvent.click(screen.getByTestId("send"));

  // The allow prompt is inline in the reasoning pane (Details, open while the turn streams). The
  // same blocked tool also surfaces in the side-panel timeline, so there can be more than one Allow
  // button — clicking either triggers the same allow-on-deny flow.
  const btns = await screen.findAllByTestId("egress-allow-btn");
  fireEvent.click(btns[0]);
  await waitFor(() => expect(allow).toHaveBeenCalledWith("demo", "api.open-meteo.com"));
  await waitFor(() => expect(screen.getAllByTestId("egress-allowed").length).toBeGreaterThan(0));
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
      ...Array(13).fill(expect.any(Function)),
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
        elapsed_ms: 1500,
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
      ...Array(13).fill(expect.any(Function)),
    ),
  );

  // Switch to Off -> reasoning off, think false.
  fireEvent.change(screen.getByTestId("reasoning-select"), { target: { value: "off" } });
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "again" } });
  fireEvent.click(screen.getByTestId("send"));
  await waitFor(() =>
    expect(stream).toHaveBeenCalledWith(
      expect.objectContaining({ reasoning: "off", think: false }),
      ...Array(13).fill(expect.any(Function)),
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

test("a draft answer goes to the reasoning trace, not the output bubble (#393)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "streamChat").mockImplementation(
    async (_p, onDelta, _c, _t, _u, _th, _e, _ap, _as, _ctx, _v, onDraft) => {
      onDraft?.({ text: "DRAFT_TEXT", attempt: 1 }); // researcher draft -> reasoning pane
      onDelta("FINAL_TEXT"); // finalize -> output bubble
    },
  );
  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "hi" } });
  fireEvent.click(screen.getByTestId("send"));

  // The output bubble shows the finalized answer.
  await waitFor(() => expect(screen.getByText("FINAL_TEXT")).toBeInTheDocument());
  // The draft lives ONLY in the reasoning Details (auto-open while streaming), not the bubble:
  // its text appears exactly once, inside the draft row.
  expect(screen.getByTestId("details-draft")).toHaveTextContent("DRAFT_TEXT");
  expect(screen.getAllByText(/DRAFT_TEXT/)).toHaveLength(1);
});

test("durable human gate: shows approve/reject and resumes on approve", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  // The turn suspends at the human gate (approval_request). Per #393 the draft answer is NOT
  // streamed to the output bubble; it's carried in the approval payload and shown in the gate.
  vi.spyOn(api, "streamChat").mockImplementation(
    async (_p, _onDelta, _onCit, _onTool, _onUsage, _onThink, _onError, onApproval) => {
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

test("egress gate: shows the egress UI (not the answer box) and resumes with the egress verb + provider", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  // The turn streams a draft answer then suspends at the egress gate (a tool hit a blocked host).
  vi.spyOn(api, "streamChat").mockImplementation(
    async (_p, onDelta, _onCit, _onTool, _onUsage, _onThink, _onError, onApproval) => {
      onDelta("draft answer");
      onApproval?.({
        run_id: "r2",
        reason: "egress_approval",
        blocked_host: "api.example.com",
        tool: "http_fetch",
        args: { url: "https://api.example.com/data" },
      });
    },
  );
  const resume = vi
    .spyOn(api, "resumeChat")
    .mockImplementation(async (_p, onDelta) => onDelta("final answer"));

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "fetch it" } });
  fireEvent.click(screen.getByTestId("send"));

  // The egress affordance appears (with the host) instead of the answer approve/reject box.
  await waitFor(() => expect(screen.getByTestId("egress-approval")).toBeInTheDocument());
  expect(screen.getByTestId("egress-host")).toHaveTextContent("api.example.com");
  expect(screen.queryByTestId("approval-request")).not.toBeInTheDocument();

  // Allowing once resumes with the egress verb and forwards the chat's provider.
  fireEvent.click(screen.getByTestId("egress-allow-once"));
  await waitFor(() =>
    expect(resume).toHaveBeenCalledWith(
      expect.objectContaining({ runId: "r2", decision: "egress_allow_once", provider: "ollama" }),
      ...Array(3).fill(expect.any(Function)),
    ),
  );
  await waitFor(() => expect(screen.getByText(/final answer/)).toBeInTheDocument());
  expect(screen.queryByTestId("egress-approval")).not.toBeInTheDocument();
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

// --- #412: the Stop button ----------------------------------------------------------------------

test("while streaming, the Send slot becomes a red Stop button; aborting returns to Send", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  // A stream that stays in flight until its AbortSignal fires, then rejects like a real abort.
  vi.spyOn(api, "streamChat").mockImplementation(
    (params, onDelta) =>
      new Promise((_resolve, reject) => {
        onDelta("partial answer"); // some text streamed before the stop
        params.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      }),
  );

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "hi" } });
  fireEvent.click(screen.getByTestId("send"));

  // Streaming: the Send button is replaced by Stop (red square, aria-label "Stop generating").
  const stop = await screen.findByTestId("stop-generation");
  expect(stop).toHaveAttribute("aria-label", "Stop generating");
  expect(stop).toHaveStyle({ color: "#b00020" });
  expect(screen.queryByTestId("send")).toBeNull();
  expect(screen.getByTestId("msg-assistant")).toHaveTextContent("partial answer");

  // Click Stop: the abort fires, the partial stays, and the slot returns to Send.
  fireEvent.click(stop);
  await waitFor(() => expect(screen.getByTestId("send")).toBeInTheDocument());
  expect(screen.getByTestId("msg-assistant")).toHaveTextContent("partial answer");
  // The amber "Generation stopped." marker shows (live), and the SR status announces it.
  expect(screen.getByTestId("stopped-marker")).toHaveTextContent("Generation stopped.");
  expect(screen.getByTestId("stop-status")).toHaveTextContent("Generation stopped.");
});

test("Escape stops an in-flight generation (no chip panel open)", async () => {
  mockProviders();
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "streamChat").mockImplementation(
    (params, onDelta) =>
      new Promise((_resolve, reject) => {
        onDelta("streaming");
        params.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      }),
  );
  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "hi" } });
  fireEvent.click(screen.getByTestId("send"));
  await screen.findByTestId("stop-generation");

  fireEvent.keyDown(document, { key: "Escape" });
  await waitFor(() => expect(screen.getByTestId("send")).toBeInTheDocument());
  expect(screen.getByTestId("stopped-marker")).toBeInTheDocument();
});

// --- #441: the cross-chat copy buffer -----------------------------------------------------------

test("Copy in chat A rehydrates the composer so it can be re-sent (cross-chat buffer)", async () => {
  vi.spyOn(api, "fetchProviders").mockResolvedValue({ default: "ollama", providers: ["ollama"] });
  vi.spyOn(api, "fetchFiles").mockResolvedValue([]);
  vi.spyOn(api, "fetchMemories").mockResolvedValue([]);
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchConversations").mockResolvedValue([CONV]);
  // Chat A (CONV) has one persisted question with a stable id + a document resource.
  vi.spyOn(api, "fetchConversation").mockResolvedValue({
    id: "c1",
    title: "Old chat",
    messages: [
      {
        id: 42,
        role: "user",
        content: "folded",
        displayContent: "Summarize the deck",
        documents: [{ name: "deck.pdf", text: "slide one" }],
      },
      { role: "assistant", content: "done" },
    ],
  });
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );
  // Open chat A and Copy its question into the (empty) composer.
  fireEvent.click(await screen.findByText("Old chat"));
  await screen.findByTestId("msg-user");
  fireEvent.click(screen.getByTestId("question-copy-0"));

  // The composer is rehydrated with the question text + the re-attached document chip.
  await waitFor(() =>
    expect((screen.getByTestId("composer") as HTMLTextAreaElement).value).toBe("Summarize the deck"),
  );
  expect(screen.getByTestId("document-attachments")).toHaveTextContent("deck.pdf");
  // Secondary path: the plain text is also placed on the clipboard.
  expect(writeText).toHaveBeenCalledWith("Summarize the deck");
});

test("Copy onto a NON-empty composer asks to replace; Replace applies, Cancel keeps the draft (#441)", async () => {
  vi.spyOn(api, "fetchProviders").mockResolvedValue({ default: "ollama", providers: ["ollama"] });
  vi.spyOn(api, "fetchFiles").mockResolvedValue([]);
  vi.spyOn(api, "fetchMemories").mockResolvedValue([]);
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchConversations").mockResolvedValue([CONV]);
  vi.spyOn(api, "fetchConversation").mockResolvedValue({
    id: "c1",
    title: "Old chat",
    messages: [
      { id: 42, role: "user", content: "folded", displayContent: "Summarize the deck" },
      { role: "assistant", content: "done" },
    ],
  });
  Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );
  // Type a half-finished draft FIRST, so a Copy must not silently destroy it.
  fireEvent.change(screen.getByTestId("composer"), { target: { value: "my own half-typed text" } });

  fireEvent.click(await screen.findByText("Old chat"));
  await screen.findByTestId("msg-user");
  fireEvent.click(screen.getByTestId("question-copy-0"));

  // The composer is NOT overwritten; an inline replace-confirm appears instead.
  expect((screen.getByTestId("composer") as HTMLTextAreaElement).value).toBe("my own half-typed text");
  const confirm = await screen.findByTestId("copy-replace-confirm");
  expect(confirm).toHaveTextContent(/replace/i);

  // Cancel keeps the draft and dismisses the prompt.
  fireEvent.click(screen.getByTestId("copy-replace-cancel"));
  expect(screen.queryByTestId("copy-replace-confirm")).toBeNull();
  expect((screen.getByTestId("composer") as HTMLTextAreaElement).value).toBe("my own half-typed text");

  // Copy again, then Replace: the draft is overwritten with the copied question.
  fireEvent.click(screen.getByTestId("question-copy-0"));
  fireEvent.click(await screen.findByTestId("copy-replace-yes"));
  await waitFor(() =>
    expect((screen.getByTestId("composer") as HTMLTextAreaElement).value).toBe("Summarize the deck"),
  );
  expect(screen.queryByTestId("copy-replace-confirm")).toBeNull();
});

test("Edit truncates from the turn, reloads, and re-runs the edited question (#441)", async () => {
  vi.spyOn(api, "fetchProviders").mockResolvedValue({ default: "ollama", providers: ["ollama"] });
  vi.spyOn(api, "fetchFiles").mockResolvedValue([]);
  vi.spyOn(api, "fetchMemories").mockResolvedValue([]);
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchConversations").mockResolvedValue([CONV]);
  // First load: the original two-turn history. After truncate, the conversation is reloaded with
  // just the (kept) earlier turn — here the edited question's turn is the first, so truncating it
  // leaves an empty history that the resubmit then rebuilds.
  const fetchConversation = vi
    .spyOn(api, "fetchConversation")
    .mockResolvedValueOnce({
      id: "c1",
      title: "Old chat",
      messages: [
        { id: 42, role: "user", content: "old question" },
        { id: 43, role: "assistant", content: "old answer" },
      ],
    })
    .mockResolvedValue({ id: "c1", title: "Old chat", messages: [] });
  const truncate = vi
    .spyOn(api, "truncateConversation")
    .mockResolvedValue({ deletedCount: 2 });
  const stream = vi.spyOn(api, "streamChat").mockImplementation(async (_p, onDelta) => {
    onDelta("new answer");
  });

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );
  fireEvent.click(await screen.findByText("Old chat"));
  await screen.findByTestId("msg-user");

  // Edit the question, change the text, and resubmit.
  fireEvent.click(screen.getByTestId("question-edit-0"));
  fireEvent.change(screen.getByTestId("question-edit-input"), {
    target: { value: "edited question" },
  });
  fireEvent.click(screen.getByTestId("edit-resubmit"));

  // The truncate targets the question's stable id (42), then the edited text re-runs via streamChat.
  await waitFor(() => expect(truncate).toHaveBeenCalledWith("demo", "c1", 42));
  await waitFor(() => expect(stream).toHaveBeenCalled());
  const last = stream.mock.calls[0][0].messages.at(-1);
  expect(last?.content).toBe("edited question");
  expect(fetchConversation).toHaveBeenCalledTimes(2); // initial open + post-truncate reload
  await waitFor(() => expect(screen.getByTestId("msg-assistant")).toHaveTextContent("new answer"));
});

test("Delete truncates from the turn and does NOT re-run (#441)", async () => {
  vi.spyOn(api, "fetchProviders").mockResolvedValue({ default: "ollama", providers: ["ollama"] });
  vi.spyOn(api, "fetchFiles").mockResolvedValue([]);
  vi.spyOn(api, "fetchMemories").mockResolvedValue([]);
  vi.spyOn(api, "fetchModels").mockResolvedValue(MODELS);
  vi.spyOn(api, "fetchConversations").mockResolvedValue([CONV]);
  vi.spyOn(api, "fetchConversation")
    .mockResolvedValueOnce({
      id: "c1",
      title: "Old chat",
      messages: [
        { id: 42, role: "user", content: "keep me" },
        { id: 43, role: "assistant", content: "keep answer" },
        { id: 44, role: "user", content: "delete me" },
        { id: 45, role: "assistant", content: "delete answer" },
      ],
    })
    .mockResolvedValue({
      id: "c1",
      title: "Old chat",
      messages: [
        { id: 42, role: "user", content: "keep me" },
        { id: 43, role: "assistant", content: "keep answer" },
      ],
    });
  const truncate = vi.spyOn(api, "truncateConversation").mockResolvedValue({ deletedCount: 2 });
  const stream = vi.spyOn(api, "streamChat");

  render(<Chat token="demo" />);
  await waitFor(() =>
    expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("qwen3.6:35b-a3b"),
  );
  fireEvent.click(await screen.findByText("Old chat"));
  await waitFor(() => expect(screen.getAllByTestId("msg-user")).toHaveLength(2));

  // Delete the SECOND question (id 44, array index 2): confirm, then it truncates from that turn.
  // The question control testids are keyed by the message's array index, not the question ordinal.
  fireEvent.click(screen.getByTestId("question-delete-2"));
  fireEvent.click(screen.getByTestId("delete-confirm-yes"));

  await waitFor(() => expect(truncate).toHaveBeenCalledWith("demo", "c1", 44));
  // Delete never re-runs the model.
  expect(stream).not.toHaveBeenCalled();
  // The truncated turn is gone; only the kept turn remains.
  await waitFor(() => expect(screen.getAllByTestId("msg-user")).toHaveLength(1));
  expect(screen.getByTestId("msg-user")).toHaveTextContent("keep me");
});
