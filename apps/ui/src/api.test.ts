import { afterEach, expect, test, vi } from "vitest";

import { streamChat } from "./api";

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
