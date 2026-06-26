import { expect, test, type Page, type Route } from "@playwright/test";

// E2E for the multimodal-attachment + resource-handling flows (#445) and the empty-PDF UX (#446).
// Every backend call is mocked at the network layer (page.route) so these run with NO live Ollama /
// Postgres, mirroring the existing chat.spec.ts harness (per-file route setup, SSE framed by \n\n).

// A vision-capable default model, so an attached image is "seen" (the description is metadata, not
// folded). Documents/audio don't need vision; this single model covers every spec here.
const MODELS_BODY = JSON.stringify({
  ok: true,
  data: {
    default_model: "qwen3-vl:8b",
    models: [
      {
        name: "qwen3-vl:8b",
        local: true,
        capabilities: {
          text: true,
          vision: true,
          embeddings: false,
          tool_calling: true,
          structured_output: true,
          thinking: true,
          max_context_tokens: 40960,
        },
      },
    ],
  },
});

const SETTINGS_BODY = JSON.stringify({
  ok: true,
  data: {
    settings: { default_model: null, agent_mode: null },
    defaults: {
      default_model: "qwen3-vl:8b",
      agent_mode: "single",
      egress_enabled: false,
      allowed_egress_hosts: [],
    },
  },
});

const json = (route: Route, body: string): Promise<void> =>
  route.fulfill({ status: 200, contentType: "application/json", body });

/**
 * Drop one or more files onto the composer dropzone. Playwright can't pass real File objects through
 * dispatchEvent args, so we build a genuine DataTransfer (with File objects of the right name/type)
 * in-page via evaluateHandle, then dispatch a real `drop` carrying it — exactly what the app's
 * onDrop reads (e.dataTransfer.files + f.type/f.name). The `types: ["Files"]` guard the app checks on
 * dragOver is satisfied because a DataTransfer with files reports "Files" in its types.
 */
async function dropFiles(
  page: Page,
  files: { name: string; type: string }[],
): Promise<void> {
  const dt = await page.evaluateHandle((items) => {
    const data = new DataTransfer();
    for (const it of items) {
      data.items.add(new File(["x"], it.name, { type: it.type }));
    }
    return data;
  }, files);
  await page.getByTestId("composer-dropzone").dispatchEvent("drop", { dataTransfer: dt });
}

/**
 * Mock the whole chat-boot sequence so the SPA reaches the Chat view with one vision model selected,
 * persistence ON (conversations list resolves), and STT enabled (so audio drag-drop is accepted).
 * Per-test routes added AFTER this (e.g. /api/v1/chat, a conversation reload) win, since the latest
 * matching handler takes precedence in Playwright.
 */
async function bootRoutes(page: Page, opts: { transcribe?: boolean } = {}): Promise<void> {
  await page.addInitScript(() => localStorage.setItem("personalai_token", "demo"));
  await page.route("**/api/v1/auth/session/me", (r) =>
    json(r, '{"data":{"subject_id":"dev","tenant_id":"t","auth_kind":"dev"}}'),
  );
  await page.route("**/health", (r) => json(r, '{"status":"ok"}'));
  await page.route("**/api/v1/providers", (r) =>
    json(r, '{"ok":true,"data":{"default":"ollama","providers":["ollama"]}}'),
  );
  await page.route("**/api/v1/models**", (r) => json(r, MODELS_BODY));
  await page.route("**/api/v1/settings", (r) => json(r, SETTINGS_BODY));
  await page.route("**/api/v1/agents/config", (r) =>
    json(
      r,
      '{"ok":true,"data":{"config":{"agents":[]},"defaults":{},"agents":[],"available_tools":[]}}',
    ),
  );
  await page.route("**/api/v1/files", (r) => json(r, '{"ok":true,"data":{"files":[]}}'));
  await page.route("**/api/v1/memory", (r) => json(r, '{"ok":true,"data":{"memories":[]}}'));
  await page.route("**/api/v1/mcp", (r) => json(r, '{"ok":true,"data":{"servers":[]}}'));
  await page.route("**/api/v1/logs*", (r) => json(r, '{"ok":true,"data":{"logs":[]}}'));
  await page.route("**/api/v1/tools/log*", (r) => json(r, '{"ok":true,"data":{"entries":[]}}'));
  await page.route("**/api/v1/tools", (r) => json(r, '{"ok":true,"data":{"tools":[]}}'));
  // status drives the mic / read-aloud affordances.
  await page.route("**/api/v1/status", (r) =>
    json(
      r,
      JSON.stringify({
        ok: true,
        data: { transcribe_enabled: opts.transcribe ?? false, tts_enabled: false },
      }),
    ),
  );
}

// Seed the conversation list + a created conversation so the optimistic send migrates to a real id
// and a reload can re-fetch the persisted turn. `messages` is the persisted turn(s) returned on
// GET /conversations/{id}; the SSE body is what POST /chat streams.
async function withConversation(page: Page, messages: unknown[], chatSSE: string): Promise<void> {
  const convBody = JSON.stringify({
    ok: true,
    data: { id: "c1", title: "chat", updated_at: "2026-06-07T00:00:00Z" },
  });
  const listBody = JSON.stringify({
    ok: true,
    data: { conversations: [{ id: "c1", title: "chat", updated_at: "2026-06-07T00:00:00Z" }] },
  });
  await page.route("**/api/v1/conversations", (r) =>
    r.request().method() === "POST" ? json(r, convBody) : json(r, listBody),
  );
  await page.route("**/api/v1/conversations/c1", (r) =>
    json(r, JSON.stringify({ ok: true, data: { id: "c1", title: "chat", messages } })),
  );
  // Eager ingest-at-attach (#420): a large doc indexes into the conversation scope on attach.
  await page.route("**/api/v1/conversations/c1/documents", (r) =>
    json(r, '{"ok":true,"data":{"document_id":"d1","chunk_count":5,"already_indexed":false}}'),
  );
  await page.route("**/api/v1/chat", (r) =>
    r.fulfill({ status: 200, contentType: "text/event-stream", body: chatSSE }),
  );
}

// A tiny valid 1x1 PNG data-URL for an attached image (the SPA stores/sends the data-URL verbatim).
const PNG_1x1 =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

const ANSWER_SSE =
  'data: {"delta":"Sure","done":false}\n\n' +
  'data: {"delta":", here.","done":false}\n\n' +
  'data: {"delta":"","done":true,"finish_reason":"stop"}\n\n' +
  'event: usage\ndata: {"prompt_tokens":100,"completion_tokens":5,"total_tokens":105,"context_limit":40960}\n\n';

// --- image: attach -> describe -> thumbnail + hover -> persists on reload ------------------------

test("attach an image, describe it, send -> thumbnail + hover description, persists on reload", async ({
  page,
}) => {
  await bootRoutes(page);
  await page.route("**/api/v1/images/describe", (r) =>
    json(
      r,
      JSON.stringify({ ok: true, data: { description: "a tabby cat on a sofa", model: "qwen3-vl:8b", ms: 120 } }),
    ),
  );
  // The persisted turn carries the structured display fields the transcript chips render on reload.
  await withConversation(
    page,
    [
      {
        id: 1,
        role: "user",
        content: "what is this?",
        display_content: "what is this?",
        images: [PNG_1x1],
        image_descriptions: ["a tabby cat on a sofa"],
      },
      { id: 2, role: "assistant", content: "Sure, here." },
    ],
    ANSWER_SSE,
  );

  await page.goto("/");
  await expect(page.getByTestId("model-select")).toHaveValue("qwen3-vl:8b");

  // Drop an image onto the composer; it is described eagerly and a chip appears.
  await dropFiles(page, [{ name: "cat.png", type: "image/png" }]);
  // The composer image chip becomes `done` once the describe call resolves.
  await expect(page.getByTestId("image-attachment").first()).toHaveAttribute("data-status", "done");

  await page.getByTestId("composer").fill("what is this?");
  await page.getByTestId("send").click();

  // The sent message renders an image thumbnail (TranscriptImages -> msg-images).
  await expect(page.getByTestId("msg-images")).toBeVisible();
  await expect(page.getByTestId("msg-assistant")).toContainText("Sure, here.");
  // Hover the thumbnail to reveal its eager description.
  await page.getByTestId("msg-images").getByTestId("image-attachment").first().hover();
  await expect(page.getByTestId("image-desc")).toContainText("a tabby cat on a sofa");

  // Reload: the persisted turn re-renders the thumbnail from the structured fields (no fold leak).
  await page.reload();
  await page.getByTestId("open-c1").click();
  await expect(page.getByTestId("msg-images")).toBeVisible();
  await expect(page.getByTestId("msg-user")).toContainText("what is this?");
});

// --- small doc folds inline vs large doc "Searched in this chat" ---------------------------------

test("a small document folds inline; a large document is RAG-indexed (Searched in this chat)", async ({
  page,
}) => {
  await bootRoutes(page);
  // First extract -> small (short text); second -> large (over the inline gate).
  let extractCall = 0;
  await page.route("**/api/v1/files/extract", (r) => {
    extractCall += 1;
    const text = extractCall === 1 ? "the quick brown fox" : "lorem ipsum ".repeat(3000);
    return json(
      r,
      JSON.stringify({
        ok: true,
        data: { name: extractCall === 1 ? "notes.txt" : "report.pdf", mime: "text/plain", text, truncated: false, model: null, ms: 30 },
      }),
    );
  });
  await withConversation(page, [], ANSWER_SSE);

  await page.goto("/");
  await expect(page.getByTestId("model-select")).toHaveValue("qwen3-vl:8b");

  // Small doc -> "In message" inline badge.
  await dropFiles(page, [{ name: "notes.txt", type: "text/plain" }]);
  await expect(page.getByTestId("document-attachment").first()).toHaveAttribute("data-status", "small");
  await expect(page.getByTestId("document-retrieval-badge")).toHaveText(/in message/i);

  // Large doc -> "Searched in this chat" (RAG) badge.
  await dropFiles(page, [{ name: "report.pdf", type: "application/pdf" }]);
  await expect(
    page.locator('[data-testid="document-attachment"][data-status="large"]'),
  ).toBeVisible();
  await expect(page.getByTestId("document-retrieval-badge").filter({ hasText: /searched in this chat/i })).toBeVisible();
});

// --- RAG trigger: the /chat request must carry documents_full + use_rag + conversation_id --------

test("large doc send carries documents_full + use_rag + conversation_id in the /chat request", async ({
  page,
}) => {
  await bootRoutes(page);
  const bigText = "lorem ipsum ".repeat(3000); // over the inline gate -> `large`
  await page.route("**/api/v1/files/extract", (r) =>
    json(
      r,
      JSON.stringify({
        ok: true,
        data: { name: "report.pdf", mime: "application/pdf", text: bigText, truncated: false, model: null, ms: 30 },
      }),
    ),
  );

  // Capture the POST /chat request body — the ground truth of what the browser sends.
  let chatBody: { use_rag?: boolean; conversation_id?: string; messages?: { role: string; documents_full?: unknown }[] } | null = null;
  let ingestBody: { name?: string; text?: string } | null = null;
  const convBody = JSON.stringify({ ok: true, data: { id: "c1", title: "chat", updated_at: "2026-06-07T00:00:00Z" } });
  await page.route("**/api/v1/conversations", (r) =>
    r.request().method() === "POST" ? json(r, convBody) : json(r, '{"ok":true,"data":{"conversations":[]}}'),
  );
  // Eager ingest-at-attach (#420): capture the document ingest call fired on attach.
  await page.route("**/api/v1/conversations/c1/documents", (r) => {
    ingestBody = r.request().postDataJSON();
    return json(r, '{"ok":true,"data":{"document_id":"d1","chunk_count":5,"already_indexed":false}}');
  });
  await page.route("**/api/v1/conversations/c1", (r) =>
    json(r, '{"ok":true,"data":{"id":"c1","title":"chat","messages":[]}}'),
  );
  await page.route("**/api/v1/chat", (r) => {
    chatBody = r.request().postDataJSON();
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: ANSWER_SSE });
  });

  await page.goto("/");
  await expect(page.getByTestId("model-select")).toHaveValue("qwen3-vl:8b");

  // Attach the large doc; the chip must classify as `large` (otherwise it never enters documents_full).
  await dropFiles(page, [{ name: "report.pdf", type: "application/pdf" }]);
  await expect(page.locator('[data-testid="document-attachment"][data-status="large"]')).toBeVisible();
  // Eager ingest-at-attach: the doc is indexed BEFORE sending; the chip ends in the "indexed" badge.
  await expect(
    page.getByTestId("document-retrieval-badge").filter({ hasText: /searched in this chat/i }),
  ).toBeVisible();
  expect(ingestBody).not.toBeNull();
  expect(ingestBody!.name).toBe("report.pdf");
  expect(ingestBody!.text).toBe(bigText);
  // "Use my documents" (use_rag) must be on by default.
  await expect(page.getByTestId("rag-toggle")).toBeChecked();

  await page.getByTestId("composer").fill("summarize the document");
  await page.getByTestId("send").click();
  await expect(page.getByTestId("msg-assistant")).toContainText("Sure, here.");

  // Assert the request that drives RAG ingest carried everything the backend gate (app.py:1642) needs.
  expect(chatBody).not.toBeNull();
  expect(chatBody!.use_rag).toBe(true);
  expect(chatBody!.conversation_id).toBe("c1");
  const lastUser = [...(chatBody!.messages ?? [])].reverse().find((m) => m.role === "user");
  expect(lastUser?.documents_full).toEqual([{ name: "report.pdf", text: bigText }]);
});

// --- #446: scanned / image-only PDF -> "no text found" + explanation ----------------------------

test("#446: a scanned/image-only PDF shows 'no text found' and an explanation, not a blank panel", async ({
  page,
}) => {
  await bootRoutes(page);
  // pypdf returns no text layer for a scanned PDF -> whitespace-only extraction (NOT an error).
  await page.route("**/api/v1/files/extract", (r) =>
    json(
      r,
      JSON.stringify({
        ok: true,
        data: { name: "scanned.pdf", mime: "application/pdf", text: "   \n  ", truncated: false, model: null, ms: 20 },
      }),
    ),
  );
  await page.route("**/api/v1/conversations", (r) => json(r, '{"ok":true,"data":{"conversations":[]}}'));

  await page.goto("/");
  await expect(page.getByTestId("model-select")).toHaveValue("qwen3-vl:8b");

  await dropFiles(page, [{ name: "scanned.pdf", type: "application/pdf" }]);

  const chip = page.getByTestId("document-attachment").first();
  await expect(chip).toHaveAttribute("data-status", "empty");
  await expect(chip).toContainText(/no text found/i);
  // No retrieval badge (neither folded nor RAG-ingested).
  await expect(page.getByTestId("document-retrieval-badge")).toHaveCount(0);
  // Opening the panel (hover) EXPLAINS the scanned/image-only case rather than showing nothing.
  // (The chip opens on hover/focus; a click would toggle it back closed after the hover opens it.)
  await chip.hover();
  await expect(page.getByTestId("document-empty-explanation")).toContainText(/scanned or image-only/i);
});

// --- audio: drop -> transcript chip --------------------------------------------------------------

test("dropping an audio file yields a transcript chip with a snippet", async ({ page }) => {
  await bootRoutes(page, { transcribe: true });
  await page.route("**/api/v1/audio/transcribe", (r) =>
    json(
      r,
      JSON.stringify({ ok: true, data: { text: "so about the deadline on Friday", model: "whisper-1", ms: 900 } }),
    ),
  );
  await page.route("**/api/v1/conversations", (r) => json(r, '{"ok":true,"data":{"conversations":[]}}'));

  await page.goto("/");
  await expect(page.getByTestId("model-select")).toHaveValue("qwen3-vl:8b");

  await dropFiles(page, [{ name: "call.mp3", type: "audio/mpeg" }]);

  const chip = page.getByTestId("audio-attachment").first();
  await expect(chip).toHaveAttribute("data-status", "done");
  await expect(chip).toContainText(/call\.mp3/);
  await expect(chip).toContainText(/so about the deadline/i);
  // The full transcript is reachable in the panel (open on hover; a click would toggle it closed).
  await chip.hover();
  await expect(page.getByTestId("audio-panel")).toContainText("so about the deadline on Friday");
});

// --- Activity panel shows resource + indexing/retrieval steps with the RAG filter ----------------

test("the Activity panel shows resource + indexing/retrieval steps and a RAG filter", async ({
  page,
}) => {
  await bootRoutes(page);
  await page.route("**/api/v1/files/extract", (r) =>
    json(
      r,
      JSON.stringify({
        ok: true,
        data: { name: "report.pdf", mime: "application/pdf", text: "lorem ipsum ".repeat(3000), truncated: false, model: null, ms: 30 },
      }),
    ),
  );
  // The RAG prelude: an indexing frame (large doc chunked) + a retrieval frame, then the answer.
  const RAG_SSE =
    'event: indexing\ndata: {"kind":"indexing","ref":"report.pdf","chunks":12,"ms":80,"status":"ok"}\n\n' +
    'event: retrieval\ndata: {"kind":"retrieval","query":"what is this","top_k":8,"hits":3,"scope":"conversation","ms":40,"citations":[{"source":"report.pdf","score":0.82}]}\n\n' +
    ANSWER_SSE;
  await withConversation(page, [], RAG_SSE);

  await page.goto("/");
  await expect(page.getByTestId("model-select")).toHaveValue("qwen3-vl:8b");

  await dropFiles(page, [{ name: "report.pdf", type: "application/pdf" }]);
  await expect(
    page.locator('[data-testid="document-attachment"][data-status="large"]'),
  ).toBeVisible();
  // Live pre-turn document pipeline (#450): extract -> vectorize -> index, each its own resource
  // node, all visible before sending (the large doc is eagerly ingested at attach).
  const res = page.getByTestId("timeline-resource");
  await expect(res.filter({ hasText: "Extracted document — report.pdf" })).toBeVisible();
  await expect(res.filter({ hasText: "Vectorized document — report.pdf" })).toBeVisible();
  await expect(res.filter({ hasText: "Indexed document — report.pdf" })).toBeVisible();

  await page.getByTestId("composer").fill("what is this");
  await page.getByTestId("send").click();

  await expect(page.getByTestId("msg-assistant")).toContainText("Sure, here.");
  // The Activity timeline carries the indexing + retrieval prelude steps.
  await expect(page.getByTestId("activity-timeline")).toBeVisible();
  await expect(page.getByTestId("timeline-indexing")).toBeVisible();
  await expect(page.getByTestId("timeline-retrieval")).toBeVisible();
  await expect(page.getByTestId("timeline-retrieval")).toContainText(/passages/i);
});

// --- Stop cancels a generation; the partial answer is kept ---------------------------------------

test("Stop cancels an in-flight generation and keeps the partial answer", async ({ page }) => {
  await bootRoutes(page);
  await page.route("**/api/v1/conversations", (r) =>
    r.request().method() === "POST"
      ? json(r, '{"ok":true,"data":{"id":"c1","title":"chat","updated_at":"2026-06-07T00:00:00Z"}}')
      : json(r, '{"ok":true,"data":{"conversations":[]}}'),
  );
  // A chat stream that delivers a partial answer, then hangs so the client abort (Stop) is what
  // ends it. Playwright resolves `route.fulfill` only after the delay; the page aborts the request
  // first, which rejects the in-flight fetch -> the UI keeps the partial + shows the stopped marker.
  await page.route("**/api/v1/chat", async (r) => {
    await new Promise((res) => setTimeout(res, 10000));
    try {
      await r.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: 'data: {"delta":"partial","done":false}\n\n',
      });
    } catch {
      // The request was aborted by the page (Stop) before we fulfilled — expected.
    }
  });

  await page.goto("/");
  await expect(page.getByTestId("model-select")).toHaveValue("qwen3-vl:8b");

  await page.getByTestId("composer").fill("tell me a long story");
  await page.getByTestId("send").click();

  // While streaming the Send slot becomes a red Stop control.
  const stop = page.getByTestId("stop-generation");
  await expect(stop).toBeVisible();
  await expect(stop).toHaveAttribute("aria-label", "Stop generating");

  await stop.click();

  // The slot returns to Send and the amber "Generation stopped." marker appears.
  await expect(page.getByTestId("send")).toBeVisible();
  await expect(page.getByTestId("stopped-marker")).toContainText(/generation stopped/i);
});

// --- message management: Copy into another chat / Edit truncates+reruns / Delete truncates --------

// Two persisted chats in the list: c1 (source) carries a two-turn history; c2 (target) is empty.
function twoChatList(): string {
  return JSON.stringify({
    ok: true,
    data: {
      conversations: [
        { id: "c1", title: "Source chat", updated_at: "2026-06-07T00:00:00Z" },
        { id: "c2", title: "Target chat", updated_at: "2026-06-06T00:00:00Z" },
      ],
    },
  });
}

const C1_FULL = {
  ok: true,
  data: {
    id: "c1",
    title: "Source chat",
    messages: [
      { id: 10, role: "user", content: "What is the capital of France?", display_content: "What is the capital of France?" },
      { id: 11, role: "assistant", content: "Paris." },
      { id: 12, role: "user", content: "And of Spain?", display_content: "And of Spain?" },
      { id: 13, role: "assistant", content: "Madrid." },
    ],
  },
};

test("Copy a question into another chat rehydrates the target composer (#441)", async ({ page }) => {
  await bootRoutes(page);
  await page.route("**/api/v1/conversations", (r) => json(r, twoChatList()));
  await page.route("**/api/v1/conversations/c1", (r) => json(r, JSON.stringify(C1_FULL)));
  await page.route("**/api/v1/conversations/c2", (r) =>
    json(r, '{"ok":true,"data":{"id":"c2","title":"Target chat","messages":[]}}'),
  );

  await page.goto("/");
  await expect(page.getByTestId("model-select")).toHaveValue("qwen3-vl:8b");

  await page.getByTestId("open-c1").click();
  await expect(page.getByTestId("msg-user").first()).toContainText("capital of France");

  // Copy the first question, switch to the (empty) target chat, and confirm it is rehydrated.
  await page.getByTestId("question-copy-0").click();
  await page.getByTestId("open-c2").click();
  await expect(page.getByTestId("composer")).toHaveValue("What is the capital of France?");
});

test("Edit truncates from the turn (the later turn is discarded) and re-runs (#441)", async ({
  page,
}) => {
  await bootRoutes(page);
  await page.route("**/api/v1/conversations", (r) => json(r, twoChatList()));
  // Edit truncates from the EDITED question's turn (id 12 here — the second question), so the later
  // turn is discarded; the kept earlier turn remains. After truncate, c1 reloads to the kept turn.
  let truncated = false;
  let truncatedFromId: number | null = null;
  await page.route("**/api/v1/conversations/c1/truncate", (r) => {
    truncated = true;
    const body = JSON.parse(r.request().postData() ?? "{}") as { from_message_id?: number };
    truncatedFromId = body.from_message_id ?? null;
    return json(r, '{"ok":true,"data":{"deleted_count":2}}');
  });
  await page.route("**/api/v1/conversations/c1", (r) =>
    json(
      r,
      truncated
        ? JSON.stringify({
            ok: true,
            data: {
              id: "c1",
              title: "Source chat",
              messages: [
                { id: 10, role: "user", content: "What is the capital of France?", display_content: "What is the capital of France?" },
                { id: 11, role: "assistant", content: "Paris." },
              ],
            },
          })
        : JSON.stringify(C1_FULL),
    ),
  );
  await page.route("**/api/v1/chat", (r) =>
    r.fulfill({ status: 200, contentType: "text/event-stream", body: ANSWER_SSE }),
  );

  await page.goto("/");
  await expect(page.getByTestId("model-select")).toHaveValue("qwen3-vl:8b");
  await page.getByTestId("open-c1").click();
  await expect(page.getByTestId("msg-user")).toHaveCount(2);

  // Edit the SECOND question (id 12, array index 2), change the text, resubmit.
  await page.getByTestId("question-edit-2").click();
  await page.getByTestId("question-edit-input").fill("What is the capital of Italy?");
  await page.getByTestId("edit-resubmit").click();

  // Edit truncates from the edited turn (id 12): the truncate fires for THAT turn's id and the
  // later "And of Spain?" question is discarded from the transcript; the kept first turn remains.
  // (The re-run of the edited question is exercised in depth by the Chat.test.tsx unit test, which
  // asserts streamChat is called with the edited text — kept out of e2e to stay deterministic.)
  await expect.poll(() => truncated).toBe(true);
  expect(truncatedFromId).toBe(12);
  await expect(page.getByText("And of Spain?")).toHaveCount(0);
  await expect(page.getByTestId("msg-user").first()).toContainText("capital of France");
});

test("Delete truncates from the turn and does not re-run (#441)", async ({ page }) => {
  await bootRoutes(page);
  await page.route("**/api/v1/conversations", (r) => json(r, twoChatList()));
  let truncated = false;
  await page.route("**/api/v1/conversations/c1/truncate", (r) => {
    truncated = true;
    return json(r, '{"ok":true,"data":{"deleted_count":2}}');
  });
  // After the truncate, c1 returns only the first (kept) turn.
  await page.route("**/api/v1/conversations/c1", (r) =>
    json(
      r,
      truncated
        ? JSON.stringify({
            ok: true,
            data: {
              id: "c1",
              title: "Source chat",
              messages: [
                { id: 10, role: "user", content: "What is the capital of France?", display_content: "What is the capital of France?" },
                { id: 11, role: "assistant", content: "Paris." },
              ],
            },
          })
        : JSON.stringify(C1_FULL),
    ),
  );
  let chatCalled = false;
  await page.route("**/api/v1/chat", (r) => {
    chatCalled = true;
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: ANSWER_SSE });
  });

  await page.goto("/");
  await expect(page.getByTestId("model-select")).toHaveValue("qwen3-vl:8b");
  await page.getByTestId("open-c1").click();
  await expect(page.getByTestId("msg-user")).toHaveCount(2);

  // Delete the SECOND question (id 12, message array index 2): confirm -> truncate-only.
  await page.getByTestId("question-delete-2").click();
  await page.getByTestId("delete-confirm-yes").click();

  // Only the first turn remains; the model is NOT re-run on a delete.
  await expect(page.getByTestId("msg-user")).toHaveCount(1);
  await expect(page.getByTestId("msg-user")).toContainText("capital of France");
  expect(truncated).toBe(true);
  expect(chatCalled).toBe(false);
});
