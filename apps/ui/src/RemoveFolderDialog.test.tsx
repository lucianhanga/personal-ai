import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { RemoveFolderDialog } from "./RemoveFolderDialog";
import type { FolderSource } from "./api";

const FOLDER: FolderSource = {
  id: "f1",
  root_path: "/Users/me/Documents/notes",
  label: "My notes",
  enabled: true,
  status: "idle",
  status_detail: null,
  counts: { synced: 312, indexing: 4, error: 1 }, // 317 indexed
  last_scan_finished_at: null,
  created_at: "2026-06-20T00:00:00Z",
};

test("states exactly how many indexed chunks/entities are purged", () => {
  render(<RemoveFolderDialog folder={FOLDER} onConfirm={vi.fn()} onClose={vi.fn()} />);
  const dialog = screen.getByTestId("remove-folder-dialog");
  expect(dialog).toHaveAttribute("role", "dialog");
  expect(dialog).toHaveAttribute("aria-modal", "true");
  // 312 + 4 + 1 = 317 indexed items.
  expect(screen.getByTestId("remove-folder-message")).toHaveTextContent("317");
  expect(screen.getByTestId("remove-folder-message")).toHaveTextContent(/chunks\/entities/i);
});

test("default focus is Cancel (the safe action)", async () => {
  render(<RemoveFolderDialog folder={FOLDER} onConfirm={vi.fn()} onClose={vi.fn()} />);
  await waitFor(() => expect(screen.getByTestId("remove-folder-cancel")).toHaveFocus());
});

test("Cancel and Escape close without deleting", () => {
  const onConfirm = vi.fn();
  const onClose = vi.fn();
  render(<RemoveFolderDialog folder={FOLDER} onConfirm={onConfirm} onClose={onClose} />);

  fireEvent.keyDown(document, { key: "Escape" });
  expect(onClose).toHaveBeenCalledTimes(1);

  fireEvent.click(screen.getByTestId("remove-folder-cancel"));
  expect(onClose).toHaveBeenCalledTimes(2);
  // Only confirming triggers the delete.
  expect(onConfirm).not.toHaveBeenCalled();
});

test("only Remove triggers the delete (confirm gating)", async () => {
  const onConfirm = vi.fn().mockResolvedValue(undefined);
  render(<RemoveFolderDialog folder={FOLDER} onConfirm={onConfirm} onClose={vi.fn()} />);
  fireEvent.click(screen.getByTestId("remove-folder-confirm"));
  await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1));
});

test("Tab from Remove (last) wraps focus back to Cancel (first)", () => {
  render(<RemoveFolderDialog folder={FOLDER} onConfirm={vi.fn()} onClose={vi.fn()} />);
  const confirm = screen.getByTestId("remove-folder-confirm");
  confirm.focus();
  fireEvent.keyDown(document, { key: "Tab" });
  expect(screen.getByTestId("remove-folder-cancel")).toHaveFocus();
});

test("surfaces an inline error if the delete fails (dialog stays open)", async () => {
  const onConfirm = vi.fn().mockRejectedValue(new Error("boom"));
  render(<RemoveFolderDialog folder={FOLDER} onConfirm={onConfirm} onClose={vi.fn()} />);
  fireEvent.click(screen.getByTestId("remove-folder-confirm"));
  await waitFor(() => expect(screen.getByTestId("remove-folder-error")).toBeInTheDocument());
  // Still open so the user can retry.
  expect(screen.getByTestId("remove-folder-dialog")).toBeInTheDocument();
});
