import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { DocumentsPanel } from "./DocumentsPanel";
import * as api from "./api";

afterEach(() => vi.restoreAllMocks());

const DOC: api.DocumentInfo = {
  id: "d1",
  name: "geo.txt",
  mime: "text/plain",
  size_bytes: 12,
  chunk_count: 3,
  created_at: "2026-06-20T00:00:00Z",
};

function noFolders(): void {
  vi.spyOn(api, "fetchFolders").mockResolvedValue([]);
  // The third region (EntityBrowser) self-fetches on mount; stub it so it settles quietly.
  vi.spyOn(api, "fetchEntities").mockResolvedValue([]);
}

test("renders three labelled regions: individual uploads + folder sources + entities", async () => {
  noFolders();
  render(
    <DocumentsPanel token="demo" files={[]} uploading={false} onUpload={vi.fn()} onDelete={vi.fn()} />,
  );
  expect(screen.getByTestId("individual-uploads")).toHaveAttribute("aria-label", "Individual uploads");
  const folders = screen.getByTestId("folder-sources-panel");
  expect(folders).toHaveAttribute("aria-label", "Folder sources");
  expect(screen.getByTestId("entity-browser")).toHaveAttribute("aria-label", "Entities");
  // The folder region resolves to its empty state once the (mocked) fetch settles.
  await waitFor(() => expect(screen.getByTestId("folder-sources-empty")).toBeInTheDocument());
});

test("the existing upload UI is unchanged (input, empty state, then the file list)", async () => {
  noFolders();
  const { rerender } = render(
    <DocumentsPanel token="demo" files={[]} uploading={false} onUpload={vi.fn()} onDelete={vi.fn()} />,
  );
  // Existing testids preserved so Chat.test.tsx / e2e keep passing.
  expect(screen.getByTestId("file-input")).toBeInTheDocument();
  expect(screen.getByTestId("documents-empty")).toBeInTheDocument();

  rerender(
    <DocumentsPanel token="demo" files={[DOC]} uploading={false} onUpload={vi.fn()} onDelete={vi.fn()} />,
  );
  expect(screen.getByTestId("file-list")).toHaveTextContent("geo.txt");
  await waitFor(() => expect(api.fetchFolders).toHaveBeenCalled());
});

test("shows the uploading status while a file is uploading", () => {
  noFolders();
  render(
    <DocumentsPanel token="demo" files={[]} uploading onUpload={vi.fn()} onDelete={vi.fn()} />,
  );
  expect(screen.getByTestId("upload-status")).toBeInTheDocument();
  expect(screen.getByTestId("file-input")).toBeDisabled();
});

test("the folder region degrades to an offline notice when the list fetch fails", async () => {
  vi.spyOn(api, "fetchFolders").mockRejectedValue(new Error("folders request failed: 503"));
  render(
    <DocumentsPanel token="demo" files={[]} uploading={false} onUpload={vi.fn()} onDelete={vi.fn()} />,
  );
  await waitFor(() => expect(screen.getByTestId("folder-sources-offline")).toBeInTheDocument());
  // Mutating action (the add toggle) is disabled while offline.
  expect(screen.getByTestId("folder-sources-add-toggle")).toBeDisabled();
});
