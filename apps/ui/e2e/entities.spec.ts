import { expect, test, type Page, type Route } from "@playwright/test";

// E2E for the corpus-global entity browser (#451), the third Settings > Documents region. Every
// backend call is mocked at the network layer (page.route), mirroring folders.spec.ts: no live
// Ollama/Postgres. Flow: open Settings > Documents -> the Entities section lists grouped entities ->
// filter by type -> open one entity to see its source documents.

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
    json(r, '{"ok":true,"data":{"config":{"agents":[]},"defaults":{},"agents":[],"available_tools":[]}}'),
  );
  await page.route("**/api/v1/files", (r) => json(r, '{"ok":true,"data":{"files":[]}}'));
  await page.route("**/api/v1/memory", (r) => json(r, '{"ok":true,"data":{"memories":[]}}'));
  await page.route("**/api/v1/mcp", (r) => json(r, '{"ok":true,"data":{"servers":[]}}'));
  await page.route("**/api/v1/logs*", (r) => json(r, '{"ok":true,"data":{"logs":[]}}'));
  await page.route("**/api/v1/tools/log*", (r) => json(r, '{"ok":true,"data":{"entries":[]}}'));
  await page.route("**/api/v1/tools", (r) => json(r, '{"ok":true,"data":{"tools":[]}}'));
  await page.route("**/api/v1/conversations", (r) => json(r, '{"ok":true,"data":{"conversations":[]}}'));
  await page.route("**/api/v1/status", (r) =>
    json(r, '{"ok":true,"data":{"transcribe_enabled":false,"tts_enabled":false}}'),
  );
  // The folder-sources region (#458) also self-fetches; keep it empty.
  await page.route("**/api/v1/folders", (r) => json(r, '{"ok":true,"data":{"folders":[]}}'));
}

const ENTITIES = [
  { id: "e1", type: "person", name: "Ada Lovelace", mention_count: 7 },
  { id: "e2", type: "person", name: "Alan Turing", mention_count: 3 },
  { id: "e3", type: "org", name: "Acme Corp", mention_count: 5 },
];

test("the Entities section lists entities by type, filters by type, and opens an entity's detail", async ({
  page,
}) => {
  await bootRoutes(page);

  // List endpoint honours the ?type= filter the UI sends.
  await page.route("**/api/v1/entities**", (r) => {
    const type = new URL(r.request().url()).searchParams.get("type");
    const list = type ? ENTITIES.filter((e) => e.type === type) : ENTITIES;
    return json(r, JSON.stringify({ ok: true, data: { entities: list } }));
  });
  // Detail endpoint (registered AFTER the list so it wins for /entities/{id}).
  await page.route("**/api/v1/entities/*", (r) =>
    json(
      r,
      JSON.stringify({
        ok: true,
        data: {
          entity: ENTITIES[2],
          documents: ["doc-1", "doc-2"],
          edges: [{ relation: "located_in", dst_entity_id: "e1" }],
        },
      }),
    ),
  );

  await page.goto("/");
  await expect(page.getByTestId("model-select")).toHaveValue("qwen3-vl:8b");
  await page.getByTestId("nav-settings").click();

  // The Entities region lists grouped entities.
  const browser = page.getByTestId("entity-browser");
  await expect(browser).toBeVisible();
  await expect(page.getByTestId("entity-group-person")).toBeVisible();
  await expect(page.getByTestId("entity-group-org")).toBeVisible();
  await expect(page.getByText("Ada Lovelace")).toBeVisible();

  // Filter by Organizations -> only the org group remains.
  await page.getByTestId("entity-filter-org").click();
  await expect(page.getByText("Ada Lovelace")).toHaveCount(0);
  await expect(page.getByText("Acme Corp")).toBeVisible();

  // Open the entity -> its source documents appear in the detail.
  await page.getByText("Acme Corp").click();
  const detail = page.getByTestId("entity-detail");
  await expect(detail).toBeVisible();
  await expect(detail.getByTestId("entity-document").first()).toHaveText("doc-1");
  await expect(detail.getByTestId("entity-edge")).toContainText("located_in");
});
