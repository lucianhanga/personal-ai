import { expect, test, type Page } from "@playwright/test";

// A 1x1 transparent PNG as a data: URL — what the backend /images/localize endpoint returns after
// it fetches a remote image server-side. The browser only ever renders THIS, never the remote URL.
const PNG_DATA_URL =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==";

const REMOTE_IMG = "https://upload.wikimedia.org/wikipedia/commons/clinton.jpg";

// Assistant answer is a markdown image pointing at a remote URL — exactly what the model emits with
// rich output enabled. The UI must NOT load this URL directly; it localizes it server-side.
const CHAT_SSE =
  `data: {"delta":"![Bill Clinton](${REMOTE_IMG})","done":false}\n\n` +
  'data: {"delta":"","done":true,"finish_reason":"stop"}\n\n' +
  'event: usage\ndata: {"prompt_tokens":10,"completion_tokens":5,"total_tokens":15,"context_limit":32768}\n\n';

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
      default_model: "qwen3:8b",
      agent_mode: "single",
      egress_enabled: false,
      allowed_egress_hosts: [],
      rich_output_enabled: true,
    },
  },
});

/** Wire up every endpoint the app hits on load so the Chat view renders and a turn can stream. */
async function stubApp(page: Page): Promise<void> {
  await page.addInitScript(() => localStorage.setItem("personalai_token", "demo"));
  const json = (body: string) => ({ status: 200, contentType: "application/json", body });

  await page.route("**/api/v1/auth/session/me", (r) =>
    r.fulfill(json('{"data":{"subject_id":"dev","tenant_id":"t","auth_kind":"dev"}}')),
  );
  await page.route("**/health", (r) => r.fulfill(json('{"status":"ok"}')));
  await page.route("**/api/v1/providers", (r) =>
    r.fulfill(json('{"ok":true,"data":{"default":"ollama","providers":["ollama"]}}')),
  );
  await page.route("**/api/v1/models**", (r) => r.fulfill(json(MODELS_BODY)));
  await page.route("**/api/v1/files", (r) => r.fulfill(json('{"ok":true,"data":{"files":[]}}')));
  await page.route("**/api/v1/mcp", (r) =>
    r.fulfill(json('{"ok":true,"data":{"servers":[]}}')),
  );
  await page.route("**/api/v1/logs*", (r) => r.fulfill(json('{"ok":true,"data":{"logs":[]}}')));
  await page.route("**/api/v1/tools/log*", (r) =>
    r.fulfill(json('{"ok":true,"data":{"entries":[]}}')),
  );
  await page.route("**/api/v1/tools", (r) => r.fulfill(json('{"ok":true,"data":{"tools":[]}}')));
  await page.route("**/api/v1/memory", (r) =>
    r.fulfill(json('{"ok":true,"data":{"memories":[]}}')),
  );
  await page.route("**/api/v1/conversations", (r) =>
    r.request().method() === "POST"
      ? r.fulfill(json('{"ok":true,"data":{"id":"c1","title":"clinton","updated_at":"2026-06-07T00:00:00Z"}}'))
      : r.fulfill(json('{"ok":true,"data":{"conversations":[]}}')),
  );
  await page.route("**/api/v1/chat", (r) =>
    r.fulfill({ status: 200, contentType: "text/event-stream", body: CHAT_SSE }),
  );
  await page.route("**/api/v1/settings", (r) => r.fulfill(json(SETTINGS_BODY)));
  await page.route("**/api/v1/agents/config", (r) =>
    r.fulfill(
      json(
        '{"ok":true,"data":{"config":{"agents":[]},"defaults":{"planner":"p","researcher":"r","critic":"c"},"agents":[{"name":"researcher","uses_tools":true}],"available_tools":[]}}',
      ),
    ),
  );
}

async function sendClintonPrompt(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByTestId("backend-status")).toHaveText(/connected/i);
  await page.getByTestId("composer").fill("show me a picture of bill clinton");
  await page.getByTestId("send").click();
  // The assistant turn arrives carrying the markdown image.
  await expect(page.getByTestId("msg-assistant")).toBeVisible();
}

test("assistant markdown image is localized and rendered inline (no direct remote load)", async ({
  page,
}) => {
  await stubApp(page);
  // The host is already allowed: /images/localize returns the server-fetched data: URL straight away.
  let localizeCalled = false;
  await page.route("**/api/v1/images/localize", (r) => {
    localizeCalled = true;
    expect(JSON.parse(r.request().postData() ?? "{}").url).toBe(REMOTE_IMG);
    return r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, data: { data_url: PNG_DATA_URL } }),
    });
  });
  // Hard guarantee of the no-egress invariant: fail if the browser ever requests the remote image.
  let remoteHit = false;
  await page.route(REMOTE_IMG, (r) => {
    remoteHit = true;
    return r.abort();
  });

  await sendClintonPrompt(page);

  // The picture is actually displayed: an <img> whose src is the localized data: URL.
  const img = page.getByTestId("localized-image");
  await expect(img).toBeVisible();
  await expect(img).toHaveAttribute("src", PNG_DATA_URL);
  expect(localizeCalled).toBe(true);
  // The remote URL was never fetched by the browser, and no <img> points at it.
  expect(remoteHit).toBe(false);
  await expect(page.locator(`img[src="${REMOTE_IMG}"]`)).toHaveCount(0);
});

test("remote image prompts for host consent, then renders after Allow", async ({ page }) => {
  await stubApp(page);
  // First localize → needs_approval; after the host is allowed, the retry returns the data: URL.
  let allowed = false;
  await page.route("**/api/v1/images/localize", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: allowed
        ? JSON.stringify({ ok: true, data: { data_url: PNG_DATA_URL } })
        : JSON.stringify({
            ok: false,
            error: { code: "E_EGRESS_APPROVAL_NEEDED", message: "approval needed" },
            data: { needs_approval: true, host: "upload.wikimedia.org" },
          }),
    }),
  );
  await page.route("**/api/v1/settings/egress/allow", (r) => {
    allowed = true;
    return r.fulfill({ status: 200, contentType: "application/json", body: '{"ok":true,"data":{}}' });
  });

  await sendClintonPrompt(page);

  // The consent card names the host (the "ask me" step), and no actual <img> is shown yet.
  await expect(page.getByTestId("localized-image-approve")).toBeVisible();
  await expect(page.getByTestId("msg-assistant")).toContainText("upload.wikimedia.org");
  await expect(page.locator('img[data-testid="localized-image"]')).toHaveCount(0);

  // Approve the host → the retry localizes and the picture renders as a real <img>.
  await page.getByTestId("localized-image-approve").click();
  const img = page.locator('img[data-testid="localized-image"]');
  await expect(img).toBeVisible();
  await expect(img).toHaveAttribute("src", PNG_DATA_URL);
});
