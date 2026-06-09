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
  'event: tool\ndata: {"phase":"call","tool":"web_search","args":{"query":"x"}}\n\n' +
  'event: tool\ndata: {"phase":"result","tool":"web_search","ok":true,"output":{"results":[]}}\n\n' +
  'data: {"delta":"Hello","done":false}\n\n' +
  'data: {"delta":" world","done":false}\n\n' +
  'data: {"delta":"","done":true,"finish_reason":"stop"}\n\n' +
  'event: usage\ndata: {"prompt_tokens":4096,"completion_tokens":12,"total_tokens":4108,"context_limit":32768}\n\n';

const FILES_BODY = JSON.stringify({ ok: true, data: { files: [] } });

test("user can pick a model and stream a chat reply", async ({ page }) => {
  // Pre-set the API token so the Chat view renders without manual entry.
  await page.addInitScript(() => localStorage.setItem("personalai_token", "demo"));
  await page.route("**/health", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: '{"status":"ok"}' }),
  );
  await page.route("**/api/v1/providers", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: '{"ok":true,"data":{"default":"ollama","providers":["ollama","openai"]}}',
    }),
  );
  await page.route("**/api/v1/models**", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: MODELS_BODY }),
  );
  await page.route("**/api/v1/files", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: FILES_BODY }),
  );
  await page.route("**/api/v1/mcp", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: '{"ok":true,"data":{"servers":[{"name":"playwright","command":"npx","args":["-y","@playwright/mcp@latest"],"env":{},"enabled":true,"connected":true,"tools":["playwright.navigate"],"error":null}]}}',
    }),
  );
  await page.route("**/api/v1/logs*", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: '{"ok":true,"data":{"logs":[{"time":"2026-06-09T10:00:00Z","level":"INFO","logger":"personalai_backend.app","message":"started"}]}}',
    }),
  );
  await page.route("**/api/v1/tools/log*", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: '{"ok":true,"data":{"entries":[{"index":0,"type":"tool.invoke","timestamp":"2026-06-09T10:00:00Z","tool":"calculator","ok":true,"error":null,"args":{"expression":"2+2"}}]}}',
    }),
  );
  await page.route("**/api/v1/tools", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: '{"ok":true,"data":{"tools":[{"name":"calculator","version":"1.0.0","risk":"low","capabilities":[],"permissions":[],"inputs":{},"outputs":{}}]}}',
    }),
  );
  await page.route("**/api/v1/memory", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: '{"ok":true,"data":{"memories":[]}}',
    }),
  );
  await page.route("**/api/v1/conversations", (r) =>
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
  await page.route("**/api/v1/chat", (r) =>
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
  await expect(page.getByTestId("details-body")).toContainText("web_search");
  await expect(page.getByTestId("context-meter-label")).toContainText("4,096 / 32,768");

  // Memory panel opens and shows the empty state.
  await page.getByTestId("memory-show").click();
  await expect(page.getByTestId("memory-empty")).toBeVisible();

  // Tools panel opens and lists the calculator.
  await page.getByTestId("tools-show").click();
  await expect(page.getByTestId("tool-list")).toContainText("calculator");

  // Tool log opens, lists a call, and expands details on click.
  await page.getByTestId("toollog-show").click();
  await page.getByTestId("toollog-row-0").click();
  await expect(page.getByTestId("toollog-detail")).toContainText("2+2");

  // App logs panel opens and shows a log line.
  await page.getByTestId("applogs-show").click();
  await expect(page.getByTestId("applogs-panel")).toContainText("started");

  // MCP panel lists the connected server.
  await page.getByTestId("mcp-show").click();
  await expect(page.getByTestId("mcp-panel")).toContainText("playwright");

  // The panel sidebar collapses and re-expands.
  await page.getByTestId("side-toggle").click();
  await expect(page.getByTestId("side-panel")).toHaveCount(0);
  await page.getByTestId("side-toggle").click();
  await expect(page.getByTestId("side-panel")).toBeVisible();
});
