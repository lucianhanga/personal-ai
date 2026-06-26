import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import {
  FolderFileTree,
  buildFileTree,
  dirCounts,
  type DirNode,
} from "./FolderFileTree";
import type { FolderFileOut, FolderFileStatus } from "./api";

function file(rel_path: string, status: FolderFileStatus = "synced", extra: Partial<FolderFileOut> = {}): FolderFileOut {
  return {
    rel_path,
    status,
    document_id: status === "synced" ? `doc-${rel_path}` : null,
    size_bytes: 2048,
    error_code: null,
    error_detail: null,
    indexed_at: status === "synced" ? "2026-06-20T00:00:00Z" : null,
    ...extra,
  };
}

const NESTED = [
  file("readme.md"),
  file("reports/2024/q3.pdf"),
  file("reports/2024/q4.pdf"),
  file("reports/2023/q1.pdf"),
  file("notes/todo.txt"),
];

// --- pure tree builders --------------------------------------------------------------------------

test("buildFileTree derives nested directories from rel_paths (dirs before files, sorted)", () => {
  const tree = buildFileTree(NESTED);
  // Top level: directories (notes, reports) precede the root file (readme.md).
  expect(tree.map((n) => n.name)).toEqual(["notes", "reports", "readme.md"]);
  expect(tree[0].kind).toBe("dir");
  expect(tree[2].kind).toBe("file");

  const reports = tree.find((n) => n.name === "reports") as DirNode;
  expect(reports.kind).toBe("dir");
  expect(reports.path).toBe("reports");
  // reports contains the 2023 + 2024 subdirectories.
  expect(reports.children.map((c) => c.name)).toEqual(["2023", "2024"]);

  const y2024 = reports.children.find((c) => c.name === "2024") as DirNode;
  expect(y2024.path).toBe("reports/2024");
  expect(y2024.children.map((c) => c.name)).toEqual(["q3.pdf", "q4.pdf"]);
});

test("dirCounts aggregates descendant statuses across nested directories", () => {
  const tree = buildFileTree([
    file("reports/2024/q3.pdf", "synced"),
    file("reports/2024/q4.pdf", "error"),
    file("reports/2023/q1.pdf", "synced"),
  ]);
  const reports = tree.find((n) => n.name === "reports") as DirNode;
  expect(dirCounts(reports)).toEqual({ synced: 2, error: 1 });
});

// --- collapsible rendering -----------------------------------------------------------------------

test("directories are collapsed by default and expand/collapse on toggle", () => {
  render(<FolderFileTree files={NESTED} />);
  // Collapsed: the nested file rows are not rendered yet.
  expect(screen.queryByText("q3.pdf")).toBeNull();
  // The top-level dir toggles are present (notes, reports) + the root file row.
  const toggles = screen.getAllByTestId("dir-toggle");
  expect(toggles.length).toBeGreaterThanOrEqual(2);

  // Expand "reports": its subdirectories appear, files still hidden until the subdir opens.
  const reportsToggle = screen.getByText("reports").closest("button")!;
  fireEvent.click(reportsToggle);
  expect(reportsToggle).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("2024")).toBeInTheDocument();
  expect(screen.queryByText("q3.pdf")).toBeNull();

  // Expand the "2024" subdirectory: the file rows render.
  fireEvent.click(screen.getByText("2024").closest("button")!);
  expect(screen.getByText("q3.pdf")).toBeInTheDocument();
  expect(screen.getByText("q4.pdf")).toBeInTheDocument();

  // Collapse "reports" again: descendants disappear.
  fireEvent.click(reportsToggle);
  expect(screen.queryByText("2024")).toBeNull();
});

test("a directory toggle shows a rollup of its descendants' statuses", () => {
  render(
    <FolderFileTree
      files={[file("reports/a.pdf", "synced"), file("reports/b.pdf", "error")]}
    />,
  );
  const rollup = screen.getAllByTestId("dir-rollup")[0];
  expect(rollup).toHaveTextContent("1 synced");
  expect(rollup).toHaveTextContent("1 error");
});

test("expandAll opens every directory (used when a filter/search is active)", () => {
  render(<FolderFileTree files={NESTED} expandAll />);
  // All leaves visible without manual expansion.
  expect(screen.getByText("q3.pdf")).toBeInTheDocument();
  expect(screen.getByText("q1.pdf")).toBeInTheDocument();
  expect(screen.getByText("todo.txt")).toBeInTheDocument();
});

test("an error file row renders its status pill, code, and detail", () => {
  render(
    <FolderFileTree
      files={[file("broken.pdf", "error", { error_code: "E_PARSE", error_detail: "unreadable PDF" })]}
      expandAll
    />,
  );
  const row = screen.getByTestId("file-row");
  expect(row).toHaveAttribute("data-status", "error");
  expect(screen.getByTestId("file-status")).toHaveTextContent("Error");
  const err = screen.getByTestId("file-error");
  expect(err).toHaveTextContent("E_PARSE");
  expect(err).toHaveTextContent("unreadable PDF");
});

test("a synced file row links to its document_id; a non-indexed file does not", () => {
  render(
    <FolderFileTree
      files={[file("a.pdf", "synced"), file("b.pdf", "pending")]}
      expandAll
    />,
  );
  const docLinks = screen.getAllByTestId("file-document");
  expect(docLinks).toHaveLength(1);
  expect(docLinks[0]).toHaveAttribute("aria-label", expect.stringContaining("doc-a.pdf"));
});

test("renders an empty state when there are no files", () => {
  render(<FolderFileTree files={[]} />);
  expect(screen.getByTestId("file-tree-empty")).toBeInTheDocument();
});
