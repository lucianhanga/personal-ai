import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { FolderDetail } from "./FolderDetail";
import * as api from "./api";

afterEach(() => vi.restoreAllMocks());

const SRC: api.FolderSource = {
  id: "f1",
  root_path: "/Users/me/notes",
  label: "Notes",
  enabled: true,
  status: "idle",
  status_detail: null,
  counts: { synced: 5 },
  last_scan_finished_at: null,
  created_at: "2026-06-20T00:00:00Z",
};

function file(rel_path: string, status: api.FolderFileStatus = "synced", extra: Partial<api.FolderFileOut> = {}): api.FolderFileOut {
  return {
    rel_path,
    status,
    document_id: status === "synced" ? `doc-${rel_path}` : null,
    size_bytes: 1024,
    error_code: null,
    error_detail: null,
    indexed_at: null,
    ...extra,
  };
}

function mockDetail(files: api.FolderFileOut[], total: number | null = null): void {
  vi.spyOn(api, "fetchFolderDetail").mockResolvedValue({ source: SRC, files, total });
}

test("fetches and renders the file tree, with the live counts in the header", async () => {
  mockDetail([file("reports/2024/q3.pdf"), file("readme.md")]);
  render(<FolderDetail folder={SRC} token="demo" liveCounts={{ synced: 5 }} />);

  await waitFor(() => expect(screen.getByTestId("file-tree")).toBeInTheDocument());
  // Header rollup reflects the passed-in live SSE counts.
  expect(screen.getByTestId("folder-detail-rollup")).toHaveTextContent("5 synced");
  // The nested directory is rendered as a toggle (collapsed by default).
  expect(screen.getByText("reports")).toBeInTheDocument();
});

test("defaults the filter to Errors when any file errored", async () => {
  mockDetail([file("ok.pdf", "synced"), file("bad.pdf", "error", { error_code: "E_PARSE" })]);
  render(<FolderDetail folder={SRC} token="demo" liveCounts={{ synced: 1, error: 1 }} />);

  await waitFor(() => expect(screen.getByTestId("filter-errors")).toHaveAttribute("aria-pressed", "true"));
  // Only the error file is shown (the filter narrows + auto-expands).
  expect(screen.getByText("bad.pdf")).toBeInTheDocument();
  expect(screen.queryByText("ok.pdf")).toBeNull();
});

test("the status filter narrows the loaded files", async () => {
  mockDetail([file("a.pdf", "synced"), file("b.pdf", "pending")]);
  render(<FolderDetail folder={SRC} token="demo" liveCounts={{}} />);
  await waitFor(() => expect(screen.getByText("a.pdf")).toBeInTheDocument());

  fireEvent.click(screen.getByTestId("filter-synced"));
  expect(screen.getByText("a.pdf")).toBeInTheDocument();
  expect(screen.queryByText("b.pdf")).toBeNull();
  expect(screen.getByTestId("folder-detail-count")).toHaveTextContent("Showing 1 of 2 loaded");
});

test("the debounced name search narrows the tree", async () => {
  mockDetail([file("alpha.pdf"), file("beta.pdf")]);
  render(<FolderDetail folder={SRC} token="demo" liveCounts={{}} />);
  await waitFor(() => expect(screen.getByText("alpha.pdf")).toBeInTheDocument());

  fireEvent.change(screen.getByTestId("folder-file-search"), { target: { value: "alpha" } });
  // Debounced (~250ms) -> beta.pdf drops out.
  await waitFor(() => expect(screen.queryByText("beta.pdf")).toBeNull());
  expect(screen.getByText("alpha.pdf")).toBeInTheDocument();
});

test("Load more fetches the next keyset page and merges it in", async () => {
  vi.spyOn(api, "fetchFolderDetail").mockImplementation(async (_t, _id, opts) =>
    opts?.after
      ? { source: SRC, files: [file("c.pdf")], total: 3 }
      : { source: SRC, files: [file("a.pdf"), file("b.pdf")], total: 3 },
  );
  render(<FolderDetail folder={SRC} token="demo" liveCounts={{}} />);
  await waitFor(() => expect(screen.getByText("a.pdf")).toBeInTheDocument());

  // total (3) > loaded (2) -> Load more is offered.
  const more = screen.getByTestId("folder-load-more");
  expect(screen.getByTestId("folder-detail-count")).toHaveTextContent("(3 total)");
  fireEvent.click(more);

  // The next page (keyed on the last rel_path) merges in; the button disappears once fully loaded.
  await waitFor(() => expect(screen.getByText("c.pdf")).toBeInTheDocument());
  expect(screen.queryByTestId("folder-load-more")).toBeNull();
  // The Load more call used the last loaded rel_path as the keyset cursor.
  expect(api.fetchFolderDetail).toHaveBeenLastCalledWith("demo", "f1", expect.objectContaining({ after: "b.pdf" }));
});

test("the Entities tab shows the P3 placeholder", async () => {
  mockDetail([file("a.pdf")]);
  render(<FolderDetail folder={SRC} token="demo" liveCounts={{}} />);
  await waitFor(() => expect(screen.getByText("a.pdf")).toBeInTheDocument());

  fireEvent.click(screen.getByTestId("folder-detail-tab-entities"));
  expect(screen.getByTestId("folder-entities-empty")).toHaveTextContent(/knowledge-graph extraction/i);
  // The files panel is no longer shown.
  expect(screen.queryByTestId("folder-detail-files")).toBeNull();
});

test("surfaces a load error", async () => {
  vi.spyOn(api, "fetchFolderDetail").mockRejectedValue(new Error("folder detail failed: 503"));
  render(<FolderDetail folder={SRC} token="demo" liveCounts={{}} />);
  await waitFor(() => expect(screen.getByTestId("folder-detail-error")).toBeInTheDocument());
});
