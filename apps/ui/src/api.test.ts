import { afterEach, expect, test, vi } from "vitest";

import { type ApprovalRequest, resumeChat, streamChat } from "./api";

function sseResponse(chunks: string[]): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const enc = new TextEncoder();
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

afterEach(() => vi.restoreAllMocks());

test("streamChat parses deltas, surfaces errors, skips malformed, flushes the final frame", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      sseResponse([
        'data: {"delta":"Hel"}\n\n',
        'data: {"delta":"lo"}\n\nevent: error\ndata: {"error":{"message":"boom"}}\n\n',
        "data: {not valid json}\n\n", // malformed -> skipped, must not abort the stream
        'data: {"delta":"!"}', // final frame, no trailing \n\n -> must be flushed
      ]),
    ),
  );
  const deltas: string[] = [];
  const errors: string[] = [];
  await streamChat(
    { messages: [], token: "t" },
    (d) => deltas.push(d),
    undefined,
    undefined,
    undefined,
    undefined,
    (e) => errors.push(e),
  );
  expect(deltas.join("")).toBe("Hello!"); // includes the flushed final frame, malformed skipped
  expect(errors).toEqual(["boom"]);
});

test("streamChat throws on a non-ok response", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("nope", { status: 500 })));
  await expect(streamChat({ messages: [], token: "t" }, () => {})).rejects.toThrow(/chat request/);
});

test("streamChat surfaces the durable human-gate approval_request", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      sseResponse([
        'data: {"delta":"draft answer"}\n\n',
        'event: approval_request\ndata: {"run_id":"r1","answer":"draft answer","critique":"ok"}\n\n',
      ]),
    ),
  );
  const approvals: ApprovalRequest[] = [];
  await streamChat(
    { messages: [], token: "t" },
    () => {},
    undefined,
    undefined,
    undefined,
    undefined,
    undefined,
    (req) => approvals.push(req),
  );
  expect(approvals).toEqual([{ run_id: "r1", answer: "draft answer", critique: "ok" }]);
});

test("resumeChat streams the finalized answer and surfaces errors", async () => {
  const fetchMock = vi.fn(async () =>
    sseResponse(['data: {"delta":"final answer"}\n\n', 'data: {"delta":"","done":true}\n\n']),
  );
  vi.stubGlobal("fetch", fetchMock);
  const deltas: string[] = [];
  await resumeChat({ runId: "r1", decision: "approve", token: "t" }, (d) => deltas.push(d));
  expect(deltas.join("")).toBe("final answer");
  // It POSTs to the run-scoped resume endpoint with the decision.
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toContain("/api/v1/chat/r1/resume");
  expect(JSON.parse(init.body as string)).toMatchObject({ decision: "approve" });
});

test("resumeChat throws on a non-ok response", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("nope", { status: 404 })));
  await expect(
    resumeChat({ runId: "x", decision: "approve", token: "t" }, () => {}),
  ).rejects.toThrow(/resume failed/);
});
