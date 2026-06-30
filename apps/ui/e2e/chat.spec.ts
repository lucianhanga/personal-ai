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
  'event: context\ndata: {"items":[{"label":"Documents","count":1,"chars":400},{"label":"Conversation + your message","count":1,"chars":40}],"total_chars":440}\n\n' +
  'event: tool\ndata: {"phase":"call","tool":"web_search","args":{"query":"x"}}\n\n' +
  'event: tool\ndata: {"phase":"result","tool":"web_search","ok":true,"output":{"results":[]}}\n\n' +
  'data: {"delta":"Hello","done":false}\n\n' +
  'data: {"delta":" world","done":false}\n\n' +
  'data: {"delta":"","done":true,"finish_reason":"stop"}\n\n' +
  'event: usage\ndata: {"prompt_tokens":4096,"completion_tokens":12,"total_tokens":4108,"context_limit":32768}\n\n';

const FILES_BODY = JSON.stringify({ ok: true, data: { files: [] } });

test("user can stream a chat reply", async ({ page }) => {
  // Pre-set the API token so the Chat view renders without manual entry.
  await page.addInitScript(() => localStorage.setItem("personalai_token", "demo"));
  await page.route("**/api/v1/auth/session/me", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: '{"data":{"subject_id":"dev","tenant_id":"t","auth_kind":"dev"}}',
    }),
  );
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
  // Per-tenant settings (loaded on mount; PUT when a model is picked) + agent config.
  const SETTINGS_BODY = JSON.stringify({
    ok: true,
    data: {
      settings: { default_model: null, agent_mode: null },
      defaults: { default_model: "qwen3:8b", agent_mode: "single", egress_enabled: false, allowed_egress_hosts: [] },
    },
  });
  await page.route("**/api/v1/settings", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: SETTINGS_BODY }),
  );
  await page.route("**/api/v1/agents/config", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: '{"ok":true,"data":{"config":{"agents":[]},"defaults":{"planner":"p","researcher":"r","critic":"c"},"agents":[{"name":"researcher","uses_tools":true}],"available_tools":["calculator"]}}',
    }),
  );

  await page.goto("/");
  await expect(page.getByTestId("backend-status")).toHaveText(/connected/i);
  // Model/provider selection moved out of the composer into Settings -> Agents (#290); the chat
  // view just needs to be interactive here. Default-model coverage lives in Agents.test.tsx.
  await expect(page.getByTestId("composer")).toBeVisible();

  await page.getByTestId("composer").fill("hi there");
  await page.getByTestId("send").click();

  await expect(page.getByTestId("msg-user")).toContainText("hi there");
  await expect(page.getByTestId("msg-assistant")).toContainText("Hello world");
  await expect(page.getByTestId("citations")).toContainText("geo.txt");
  await expect(page.getByTestId("details-body")).toContainText("web_search");
  await expect(page.getByTestId("context-meter-label")).toContainText("4,096 / 32,768");

  // Side panel: the Activity timeline shows this turn's assembled context and its tool calls.
  await expect(page.getByTestId("activity-timeline")).toBeVisible();
  await expect(page.getByTestId("timeline-context")).toBeVisible(); // "Context assembled" node
  // Expand the tool node (collapsed by default) and confirm the request is shown.
  await page.getByTestId("toolio-summary").first().click();
  await expect(page.getByTestId("activity-timeline")).toContainText("web_search");

  // The panel sidebar collapses and re-expands.
  await page.getByTestId("side-toggle").click();
  await expect(page.getByTestId("side-panel")).toHaveCount(0);
  await page.getByTestId("side-toggle").click();
  await expect(page.getByTestId("side-panel")).toBeVisible();

  // Settings view: Memory, Tools, and MCP now live in dedicated sections.
  await page.getByTestId("nav-settings").click();
  await expect(page.getByTestId("settings-view")).toBeVisible();
  await page.getByTestId("settings-nav-memory").click();
  await expect(page.getByTestId("memory-empty")).toBeVisible();
  await page.getByTestId("settings-nav-tools").click();
  await expect(page.getByTestId("tool-list")).toContainText("calculator");
  await page.getByTestId("settings-nav-mcp").click();
  await expect(page.getByTestId("mcp-manager")).toContainText("playwright");
});
