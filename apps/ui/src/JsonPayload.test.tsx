import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { JsonPayload } from "./JsonPayload";

test("pretty-prints an object and copies the FULL raw JSON", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });

  render(<JsonPayload label="Request" value={{ query: "hello", limit: 3 }} />);
  expect(screen.getByTestId("json-payload")).toHaveTextContent("Request");
  // 2-space pretty-print.
  expect(screen.getByTestId("json-pre")).toHaveTextContent('"query": "hello"');

  fireEvent.click(screen.getByTestId("json-copy"));
  expect(writeText).toHaveBeenCalledWith(JSON.stringify({ query: "hello", limit: 3 }, null, 2));
});

test("clips a large payload and toggles show full / show less", () => {
  // A long string that exceeds the ~1.5KB preview cap.
  const big = "x".repeat(4000);
  render(<JsonPayload value={big} />);

  const pre = screen.getByTestId("json-pre");
  // Preview is clipped well under the full length.
  expect((pre.textContent ?? "").length).toBeLessThan(big.length);
  const toggle = screen.getByTestId("json-toggle");
  expect(toggle).toHaveTextContent("show full");

  fireEvent.click(toggle);
  expect(screen.getByTestId("json-pre").textContent).toHaveLength(big.length);
  expect(screen.getByTestId("json-toggle")).toHaveTextContent("show less");

  fireEvent.click(screen.getByTestId("json-toggle"));
  expect((screen.getByTestId("json-pre").textContent ?? "").length).toBeLessThan(big.length);
});

test("no toggle for a small payload (nothing to expand)", () => {
  render(<JsonPayload value={{ ok: true }} />);
  expect(screen.queryByTestId("json-toggle")).toBeNull();
});

test("handles null gracefully", () => {
  render(<JsonPayload value={null} />);
  expect(screen.getByTestId("json-pre")).toHaveTextContent("null");
});
