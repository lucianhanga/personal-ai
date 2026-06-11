import { expect, test } from "@playwright/test";

// The SPA calls the backend /health and /auth/session/me; we intercept both so the e2e is
// deterministic and needs no running Python backend. session/me returns a dev session so the app
// renders Chat (not the Login screen).

const DEV_SESSION = '{"data":{"subject_id":"dev","tenant_id":"t","auth_kind":"dev"}}';

test("renders connected when the backend is healthy", async ({ page }) => {
  await page.route("**/api/v1/auth/session/me", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: DEV_SESSION }),
  );
  await page.route("**/health", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: '{"status":"ok"}' }),
  );
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Personal AI" })).toBeVisible();
  await expect(page.getByTestId("backend-status")).toHaveText(/connected/i);
  await expect(page.getByTestId("provider-badge")).toHaveText("Local");
});

test("renders not reachable when the backend is down", async ({ page }) => {
  await page.route("**/api/v1/auth/session/me", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: DEV_SESSION }),
  );
  await page.route("**/health", (route) => route.abort());
  await page.goto("/");
  await expect(page.getByTestId("backend-status")).toHaveText(/not reachable/i);
});
