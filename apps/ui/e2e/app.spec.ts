import { expect, test } from "@playwright/test";

// The SPA calls the backend /health; we intercept it so the e2e is deterministic and needs no
// running Python backend. (M1+ can add a full integration test against the real backend.)

test("renders connected when the backend is healthy", async ({ page }) => {
  await page.route("**/health", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: '{"status":"ok"}' }),
  );
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Personal AI" })).toBeVisible();
  await expect(page.getByTestId("backend-status")).toHaveText(/connected/i);
  await expect(page.getByTestId("provider-badge")).toHaveText("Local");
});

test("renders not reachable when the backend is down", async ({ page }) => {
  await page.route("**/health", (route) => route.abort());
  await page.goto("/");
  await expect(page.getByTestId("backend-status")).toHaveText(/not reachable/i);
});
