import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { Memory } from "./Memory";
import * as api from "./api";

afterEach(() => vi.restoreAllMocks());

const MEM = {
  id: "m1",
  kind: "semantic",
  text: "Works at Hyperneers GmbH",
  confidence: 0.9,
  source: { conversation_id: "c1" },
  created_at: "2026-06-07T00:00:00Z",
  updated_at: "2026-06-07T00:00:00Z",
};

test("lists remembered facts", async () => {
  vi.spyOn(api, "fetchMemories").mockResolvedValue([MEM]);
  render(<Memory token="demo" />);
  await waitFor(() => expect(screen.getByTestId("memory-item")).toHaveTextContent("Hyperneers"));
});

test("shows empty state when nothing is remembered", async () => {
  vi.spyOn(api, "fetchMemories").mockResolvedValue([]);
  render(<Memory token="demo" />);
  await waitFor(() => expect(screen.getByTestId("memory-empty")).toBeInTheDocument());
});

test("edits a memory", async () => {
  vi.spyOn(api, "fetchMemories").mockResolvedValue([MEM]);
  const update = vi.spyOn(api, "updateMemory").mockResolvedValue();
  render(<Memory token="demo" />);
  await waitFor(() => expect(screen.getByTestId("memory-edit-m1")).toBeInTheDocument());

  fireEvent.click(screen.getByTestId("memory-edit-m1"));
  fireEvent.change(screen.getByTestId("memory-edit-input"), { target: { value: "edited" } });
  fireEvent.click(screen.getByTestId("memory-save-m1"));
  await waitFor(() => expect(update).toHaveBeenCalledWith("demo", "m1", "edited"));
});

test("deletes a memory", async () => {
  vi.spyOn(api, "fetchMemories").mockResolvedValue([MEM]);
  const del = vi.spyOn(api, "deleteMemory").mockResolvedValue();
  render(<Memory token="demo" />);
  await waitFor(() => expect(screen.getByTestId("memory-delete-m1")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("memory-delete-m1"));
  await waitFor(() => expect(del).toHaveBeenCalledWith("demo", "m1"));
});

test("forgets everything after confirm", async () => {
  vi.spyOn(api, "fetchMemories").mockResolvedValue([MEM]);
  const forget = vi.spyOn(api, "forgetAllMemory").mockResolvedValue();
  vi.stubGlobal("confirm", () => true);
  render(<Memory token="demo" />);
  await waitFor(() => expect(screen.getByTestId("memory-forget-all")).toBeEnabled());
  fireEvent.click(screen.getByTestId("memory-forget-all"));
  await waitFor(() => expect(forget).toHaveBeenCalledWith("demo"));
});

test("surfaces a load error", async () => {
  vi.spyOn(api, "fetchMemories").mockRejectedValue(new Error("memory request failed: 503"));
  render(<Memory token="demo" />);
  await waitFor(() => expect(screen.getByTestId("memory-error")).toHaveTextContent(/503/));
});
