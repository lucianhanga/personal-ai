import { expect, test } from "@playwright/test";

const MODELS_BODY = JSON.stringify({
  ok: true,
  data: {
    default_model: "qwen3:8b",
    models: [
      {
        name: "qwen3:8b",
        local: true,
        capabilities: {
          text: true,
          vision: false,
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

const CHAT_SSE =
  'event: citations\ndata: [{"n":1,"source_id":"d1","locator":"chunk 0","score":0.9,"name":"geo.txt"}]\n\n' +
  'data: {"delta":"Hello","done":false}\n\n' +
  'data: {"delta":" world","done":false}\n\n' +
  'data: {"delta":"","done":true,"finish_reason":"stop"}\n\n';

const FILES_BODY = JSON.stringify({ ok: true, data: { files: [] } });

test("user can pick a model and stream a chat reply", async ({ page }) => {
  // Pre-set the API token so the Chat view renders without manual entry.
  await page.addInitScript(() => localStorage.setItem("personalai_token", "demo"));
  await page.route("**/health", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: '{"status":"ok"}' }),
  );
  await page.route("**/api/providers", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: '{"ok":true,"data":{"default":"ollama","providers":["ollama","openai"]}}',
    }),
  );
  await page.route("**/api/models**", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: MODELS_BODY }),
  );
  await page.route("**/api/files", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: FILES_BODY }),
  );
  await page.route("**/api/conversations", (r) =>
    r.request().method() === "POST"
      ? r.fulfill({
          status: 200,
          contentType: "application/json",
          body: '{"ok":true,"data":{"id":"c1","title":"hi there","updated_at":"2026-06-07T00:00:00Z"}}',
        })
      : r.fulfill({
          status: 200,
          contentType: "application/json",
          body: '{"ok":true,"data":{"conversations":[]}}',
        }),
  );
  await page.route("**/api/chat", (r) =>
    r.fulfill({ status: 200, contentType: "text/event-stream", body: CHAT_SSE }),
  );

  await page.goto("/");
  await expect(page.getByTestId("backend-status")).toHaveText(/connected/i);
  await expect(page.getByTestId("provider-select")).toHaveValue("ollama");
  await expect(page.getByTestId("model-select")).toHaveValue("qwen3:8b");

  await page.getByTestId("composer").fill("hi there");
  await page.getByTestId("send").click();

  await expect(page.getByTestId("msg-user")).toContainText("hi there");
  await expect(page.getByTestId("msg-assistant")).toContainText("Hello world");
  await expect(page.getByTestId("citations")).toContainText("geo.txt");
});
