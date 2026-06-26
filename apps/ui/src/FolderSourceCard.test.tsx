import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { FolderSourceCard } from "./FolderSourceCard";
import * as api from "./api";

afterEach(() => vi.restoreAllMocks());

const FOLDER: api.FolderSource = {
  id: "f1",
  root_path: "/Users/me/Documents/notes",
  label: "My notes",
  enabled: true,
  status: "idle",
  status_detail: null,
  counts: { synced: 312, indexing: 4, error: 1 },
  last_scan_finished_at: "2026-06-26T00:00:00Z",
  created_at: "2026-06-20T00:00:00Z",
};

// Quiet the SSE stream so the card mounts without a real fetch.
function stubStream(): void {
  vi.spyOn(api, "streamFolderEvents").mockResolvedValue(undefined);
}

test("renders the status pill (word + color) and a non-zero-buckets rollup", () => {
  stubStream();
  render(<FolderSourceCard folder={FOLDER} token="demo" onRemove={vi.fn()} />);

  expect(screen.getByTestId("folder-status")).toHaveTextContent("Idle");
  const rollup = screen.getByTestId("folder-rollup");
  expect(rollup).toHaveTextContent("312 synced");
  expect(rollup).toHaveTextContent("4 indexing");
  expect(rollup).toHaveTextContent("1 error");
  // Zero buckets are omitted.
  expect(rollup).not.toHaveTextContent("pending");
});

test("the status pill word tracks the scan status", () => {
  stubStream();
  const { rerender } = render(
    <FolderSourceCard folder={{ ...FOLDER, status: "scanning" }} token="demo" onRemove={vi.fn()} />,
  );
  expect(screen.getByTestId("folder-status")).toHaveTextContent("Scanning");
  rerender(<FolderSourceCard folder={{ ...FOLDER, status: "error" }} token="demo" onRemove={vi.fn()} />);
  expect(screen.getByTestId("folder-status")).toHaveTextContent("Error");
  rerender(<FolderSourceCard folder={{ ...FOLDER, status: "disabled" }} token="demo" onRemove={vi.fn()} />);
  expect(screen.getByTestId("folder-status")).toHaveTextContent("Paused");
});

test("shows an empty rollup line when no files are indexed", () => {
  stubStream();
  render(<FolderSourceCard folder={{ ...FOLDER, counts: {} }} token="demo" onRemove={vi.fn()} />);
  expect(screen.getByTestId("folder-rollup")).toHaveTextContent(/no files indexed yet/i);
});

test("the live SSE stream drives the rollup + status", async () => {
  // Capture the onProgress callback so the test can push a frame as the backend would.
  const holder: { push?: (ev: api.FolderProgressEvent) => void } = {};
  vi.spyOn(api, "streamFolderEvents").mockImplementation(async (_id, onProgress) => {
    holder.push = onProgress;
  });
  render(
    <FolderSourceCard
      folder={{ ...FOLDER, status: "scanning", counts: { pending: 100 } }}
      token="demo"
      onRemove={vi.fn()}
    />,
  );
  await waitFor(() => expect(holder.push).toBeDefined());

  // A progress frame moves files from pending -> synced.
  holder.push?.({ id: "f1", status: "scanning", counts: { synced: 60, pending: 40 }, done: false });
  await waitFor(() => expect(screen.getByTestId("folder-rollup")).toHaveTextContent("60 synced"));

  // The terminal done frame settles the source to idle, fully synced.
  holder.push?.({ id: "f1", status: "idle", counts: { synced: 100 }, done: true });
  await waitFor(() => expect(screen.getByTestId("folder-status")).toHaveTextContent("Idle"));
  expect(screen.getByTestId("folder-rollup")).toHaveTextContent("100 synced");
});

test("Pause is optimistic and reverts on failure", async () => {
  stubStream();
  // A deferred rejection: the optimistic "Paused" shows before it settles, then reverts.
  const holder: { reject?: (e: unknown) => void } = {};
  vi.spyOn(api, "pauseFolder").mockReturnValue(
    new Promise<api.FolderSource>((_, r) => {
      holder.reject = r;
    }),
  );
  render(<FolderSourceCard folder={FOLDER} token="demo" onRemove={vi.fn()} />);

  fireEvent.click(screen.getByTestId("folder-pause"));
  // Optimistic: the pill flips to Paused immediately (before the API settles).
  await waitFor(() => expect(screen.getByTestId("folder-status")).toHaveTextContent("Paused"));

  holder.reject?.(new Error("network"));
  // Revert: back to Idle, with an inline error.
  await waitFor(() => expect(screen.getByTestId("folder-status")).toHaveTextContent("Idle"));
  expect(screen.getByTestId("folder-card-error")).toBeInTheDocument();
});

test("Pause then success keeps the server status", async () => {
  stubStream();
  vi.spyOn(api, "pauseFolder").mockResolvedValue({ ...FOLDER, status: "disabled" });
  render(<FolderSourceCard folder={FOLDER} token="demo" onRemove={vi.fn()} />);

  fireEvent.click(screen.getByTestId("folder-pause"));
  await waitFor(() => expect(screen.getByTestId("folder-resume")).toBeInTheDocument());
  expect(screen.getByTestId("folder-status")).toHaveTextContent("Paused");
});

test("Re-sync is disabled while scanning", () => {
  stubStream();
  render(<FolderSourceCard folder={{ ...FOLDER, status: "scanning" }} token="demo" onRemove={vi.fn()} />);
  expect(screen.getByTestId("folder-resync")).toBeDisabled();
});

test("Re-sync surfaces E_FOLDER_PAUSED inline (does not throw)", async () => {
  stubStream();
  vi.spyOn(api, "resyncFolder").mockResolvedValue({
    ok: false,
    error: { code: "E_FOLDER_PAUSED", message: "This source is paused. Resume it to re-sync." },
  });
  render(<FolderSourceCard folder={{ ...FOLDER, status: "disabled" }} token="demo" onRemove={vi.fn()} />);

  fireEvent.click(screen.getByTestId("folder-resync"));
  await waitFor(() =>
    expect(screen.getByTestId("folder-resync-notice")).toHaveTextContent(/paused/i),
  );
});

test("Remove opens the confirm dialog; confirming calls onRemove", async () => {
  stubStream();
  const onRemove = vi.fn().mockResolvedValue(undefined);
  render(<FolderSourceCard folder={FOLDER} token="demo" onRemove={onRemove} />);

  expect(screen.queryByTestId("remove-folder-dialog")).toBeNull();
  fireEvent.click(screen.getByTestId("folder-remove"));
  expect(screen.getByTestId("remove-folder-dialog")).toBeInTheDocument();

  fireEvent.click(screen.getByTestId("remove-folder-confirm"));
  await waitFor(() => expect(onRemove).toHaveBeenCalledWith("f1"));
});

test("exposes the full path in title + aria-label (truncated in view)", () => {
  stubStream();
  render(<FolderSourceCard folder={FOLDER} token="demo" onRemove={vi.fn()} />);
  const path = screen.getByTestId("folder-path");
  expect(path).toHaveAttribute("title", "/Users/me/Documents/notes");
  expect(path).toHaveAttribute("aria-label", "/Users/me/Documents/notes");
});
