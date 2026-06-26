import { expect, test, type Page, type Route } from "@playwright/test";

// E2E for Settings > Documents v2 — folder sources (#458). Every backend call is mocked at the
// network layer (page.route), mirroring attachments.spec.ts: no live Ollama/Postgres, SSE framed by
// \n\n. Flow: add a folder via the form -> card appears -> the SSE stream drives the rollup to
// synced -> pause -> resume -> remove via the confirm dialog -> card gone.

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

async function bootRoutes(page: Page): Promise<void> {
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
  await page.route("**/api/v1/conversations", (r) =>
    json(r, '{"ok":true,"data":{"conversations":[]}}'),
  );
  await page.route("**/api/v1/status", (r) =>
    json(r, '{"ok":true,"data":{"transcribe_enabled":false,"tts_enabled":false}}'),
  );
}

// A registered folder source, in a given status with given counts.
type Counts = Record<string, number>;
function folderOut(status: string, counts: Counts): string {
  return JSON.stringify({
    id: "f1",
    root_path: "/Users/me/Documents/notes",
    label: "My notes",
    enabled: status !== "disabled",
    status,
    status_detail: null,
    counts,
    last_scan_finished_at: null,
    created_at: "2026-06-26T00:00:00Z",
  });
}

// The SSE body that drives the live rollup to fully-synced, terminating with a `done` frame.
const EVENTS_SSE =
  'event: progress\ndata: {"id":"f1","status":"scanning","counts":{"pending":2,"synced":1}}\n\n' +
  'event: progress\ndata: {"id":"f1","status":"scanning","counts":{"synced":3}}\n\n' +
  'event: done\ndata: {"id":"f1","status":"idle","counts":{"synced":3}}\n\n';

test("add a folder source, watch it sync over SSE, pause/resume, then remove it", async ({
  page,
}) => {
  await bootRoutes(page);

  // Stateful folder list: empty until the POST registers f1, then it lists f1.
  let registered = false;
  await page.route("**/api/v1/folders", (r) => {
    if (r.request().method() === "POST") {
      registered = true;
      // Newly registered: scanning, nothing indexed yet (the SSE then drives it to synced).
      return json(r, JSON.stringify({ ok: true, data: JSON.parse(folderOut("scanning", { pending: 2 })) }));
    }
    return json(
      r,
      registered
        ? JSON.stringify({ ok: true, data: { folders: [JSON.parse(folderOut("scanning", { pending: 2 }))] } })
        : '{"ok":true,"data":{"folders":[]}}',
    );
  });

  // The live progress stream. Delayed slightly so the post-add list refresh resets the card first,
  // then the SSE frames land last and win — keeping the "drives to synced" assertion deterministic.
  await page.route("**/api/v1/folders/*/events", async (r) => {
    await new Promise((res) => setTimeout(res, 150));
    await r.fulfill({ status: 200, contentType: "text/event-stream", body: EVENTS_SSE });
  });
  await page.route("**/api/v1/folders/*/pause", (r) =>
    json(r, JSON.stringify({ ok: true, data: JSON.parse(folderOut("disabled", { synced: 3 })) })),
  );
  await page.route("**/api/v1/folders/*/resume", (r) =>
    json(r, JSON.stringify({ ok: true, data: JSON.parse(folderOut("idle", { synced: 3 })) })),
  );
  await page.route("**/api/v1/folders/*", (r) => {
    if (r.request().method() === "DELETE") {
      registered = false; // the subsequent list refresh returns empty -> card gone
      return json(r, '{"ok":true,"data":{"purged_documents":3}}');
    }
    return json(r, JSON.stringify({ ok: true, data: JSON.parse(folderOut("idle", { synced: 3 })) }));
  });

  await page.goto("/");
  await expect(page.getByTestId("model-select")).toHaveValue("qwen3-vl:8b");

  // Go to Settings > Documents (the default section); the folder region renders its empty state.
  await page.getByTestId("nav-settings").click();
  await expect(page.getByTestId("folder-sources-panel")).toBeVisible();
  await expect(page.getByTestId("folder-sources-empty")).toBeVisible();

  // Open the add form, register a folder.
  await page.getByTestId("folder-sources-add-toggle").click();
  await page.getByTestId("folder-add-path").fill("/Users/me/Documents/notes");
  await page.getByTestId("folder-add-label").fill("My notes");
  await page.getByTestId("folder-add-submit").click();

  // The card appears; the SSE stream drives the rollup to "3 synced" and the pill to Idle.
  const card = page.getByTestId("folder-card");
  await expect(card).toBeVisible();
  await expect(page.getByTestId("folder-rollup")).toContainText("3 synced");
  await expect(page.getByTestId("folder-status")).toHaveText("Idle");

  // Pause -> the control flips to Resume and the pill reads Paused.
  await page.getByTestId("folder-pause").click();
  await expect(page.getByTestId("folder-resume")).toBeVisible();
  await expect(page.getByTestId("folder-status")).toHaveText("Paused");

  // Resume -> back to a Pause control.
  await page.getByTestId("folder-resume").click();
  await expect(page.getByTestId("folder-pause")).toBeVisible();

  // Remove -> the confirm dialog states what is purged; only confirming triggers the DELETE.
  await page.getByTestId("folder-remove").click();
  const dialog = page.getByTestId("remove-folder-dialog");
  await expect(dialog).toBeVisible();
  await expect(page.getByTestId("remove-folder-message")).toContainText("3");
  await page.getByTestId("remove-folder-confirm").click();

  // The card is gone and the empty state returns.
  await expect(page.getByTestId("folder-card")).toHaveCount(0);
  await expect(page.getByTestId("folder-sources-empty")).toBeVisible();
});

test("a register error (E_FOLDER_NOT_FOUND) shows inline; the card is not added", async ({
  page,
}) => {
  await bootRoutes(page);
  await page.route("**/api/v1/folders", (r) => {
    if (r.request().method() === "POST") {
      return r.fulfill({
        status: 400,
        contentType: "application/json",
        body: '{"ok":false,"error":{"code":"E_FOLDER_NOT_FOUND","message":"That folder does not exist."}}',
      });
    }
    return json(r, '{"ok":true,"data":{"folders":[]}}');
  });

  await page.goto("/");
  await expect(page.getByTestId("model-select")).toHaveValue("qwen3-vl:8b");
  await page.getByTestId("nav-settings").click();

  await page.getByTestId("folder-sources-add-toggle").click();
  await page.getByTestId("folder-add-path").fill("/does/not/exist");
  await page.getByTestId("folder-add-submit").click();

  await expect(page.getByTestId("folder-add-error")).toContainText("does not exist");
  await expect(page.getByTestId("folder-card")).toHaveCount(0);
});
