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

function mockFetch(impl: () => Promise<Response> | Response): void {
  vi.stubGlobal("fetch", vi.fn(impl));
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

test("renders the local provider badge and the security note", () => {
  mockFetch(() => new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
  render(<App />);
  expect(screen.getByTestId("provider-badge")).toHaveTextContent("Local");
  expect(screen.getByTestId("security-note")).toHaveTextContent(/egress is disabled/i);
});
