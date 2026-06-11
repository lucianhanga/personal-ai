import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { App, readToken } from "./App";

const TOKEN_KEY = "personalai_token";

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

test("readToken prefers sessionStorage", () => {
  sessionStorage.setItem(TOKEN_KEY, "sess");
  expect(readToken()).toBe("sess");
});

test("readToken migrates a legacy localStorage token into sessionStorage and clears it", () => {
  localStorage.setItem(TOKEN_KEY, "legacy");
  expect(readToken()).toBe("legacy");
  expect(sessionStorage.getItem(TOKEN_KEY)).toBe("legacy");
  expect(localStorage.getItem(TOKEN_KEY)).toBeNull(); // no persistent copy left behind
});

// Route /auth/session/me to a dev session so the app renders Chat (not the Login screen); all other
// requests use the provided impl. Tests that reject `impl` still get an authed session + a
// disconnected health badge.
function mockFetch(impl: () => Promise<Response> | Response): void {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string | URL) => {
      if (String(url).includes("/auth/session/me")) {
        return new Response(
          JSON.stringify({ data: { subject_id: "dev", tenant_id: "t", auth_kind: "dev" } }),
          { status: 200 },
        );
      }
      return impl();
    }),
  );
}

test("shows connected when the backend is healthy", async () => {
  mockFetch(() => new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
  render(<App />);
  await waitFor(() =>
    expect(screen.getByTestId("backend-status")).toHaveTextContent(/connected/i),
  );
});

test("shows not reachable when the backend fails", async () => {
  mockFetch(() => Promise.reject(new Error("network down")));
  render(<App />);
  await waitFor(() =>
    expect(screen.getByTestId("backend-status")).toHaveTextContent(/not reachable/i),
  );
});

test("renders the local provider badge and the security note", async () => {
  mockFetch(() => new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
  render(<App />);
  // Chat renders after the session resolves (the app gates on /auth/session/me now).
  expect(await screen.findByTestId("provider-badge")).toHaveTextContent("Local");
  expect(screen.getByTestId("security-note")).toHaveTextContent(/egress is disabled/i);
});

test("shows the login screen when the session is unauthenticated (401)", async () => {
  // /session/me returns 401 -> hosted, not logged in -> Login screen instead of Chat.
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string | URL) => {
      if (String(url).includes("/auth/session/me")) return new Response(null, { status: 401 });
      return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
    }),
  );
  render(<App />);
  expect(await screen.findByTestId("login-form")).toBeInTheDocument();
});
