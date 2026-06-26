import { useState } from "react";

import type { FolderCounts, FolderFileOut } from "./api";
import { FileStatusPill, MUTED, RED, StatusRollup, formatBytes, formatWhen } from "./folderUi";

// --- tree model (pure; exported for unit tests) --------------------------------------------------

export interface FileLeaf {
  kind: "file";
  name: string; // basename
  path: string; // full POSIX rel_path
  file: FolderFileOut;
}

export interface DirNode {
  kind: "dir";
  name: string; // this segment's name
  path: string; // full path to this directory (e.g. "reports/2024")
  children: TreeNode[];
}

export type TreeNode = DirNode | FileLeaf;

function sortDir(node: DirNode): void {
  node.children.sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === "dir" ? -1 : 1; // directories first
    return a.name.localeCompare(b.name);
  });
  for (const c of node.children) if (c.kind === "dir") sortDir(c);
}

/** Build a nested directory tree from a flat list of files, deriving directories from each
 * `rel_path`'s segments (a watched folder is a TREE, not a flat list). Returns the root's children;
 * directories come before files, each level alphabetical. */
export function buildFileTree(files: FolderFileOut[]): TreeNode[] {
  const root: DirNode = { kind: "dir", name: "", path: "", children: [] };
  const dirIndex = new Map<string, DirNode>([["", root]]);

  for (const file of files) {
    const segs = file.rel_path.split("/").filter(Boolean);
    if (segs.length === 0) continue;
    let parent = root;
    let prefix = "";
    // Walk/create the intermediate directory nodes.
    for (let i = 0; i < segs.length - 1; i++) {
      prefix = prefix ? `${prefix}/${segs[i]}` : segs[i];
      let dir = dirIndex.get(prefix);
      if (!dir) {
        dir = { kind: "dir", name: segs[i], path: prefix, children: [] };
        dirIndex.set(prefix, dir);
        parent.children.push(dir);
      }
      parent = dir;
    }
    parent.children.push({ kind: "file", name: segs[segs.length - 1], path: file.rel_path, file });
  }

  sortDir(root);
  return root.children;
}

/** Aggregate the status counts of every file under a directory node (for its rollup line). */
export function dirCounts(node: DirNode): FolderCounts {
  const counts: FolderCounts = {};
  const walk = (n: TreeNode): void => {
    if (n.kind === "file") {
      counts[n.file.status] = (counts[n.file.status] ?? 0) + 1;
    } else {
      for (const c of n.children) walk(c);
    }
  };
  walk(node);
  return counts;
}

// --- rendering -----------------------------------------------------------------------------------

function copyDocId(id: string): void {
  void navigator.clipboard?.writeText(id).catch(() => undefined);
}

/** A single file row: status pill, name, size, indexed date, a document affordance, and (on error)
 * the error code/detail. */
function FileRow({ leaf, depth }: { leaf: FileLeaf; depth: number }): React.ReactElement {
  const f = leaf.file;
  return (
    <li
      data-testid="file-row"
      data-rel-path={f.rel_path}
      data-status={f.status}
      style={{ listStyle: "none", padding: "0.2rem 0", paddingLeft: `${depth * 1.1 + 0.2}rem` }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
        <FileStatusPill status={f.status} />
        <span
          style={{
            color: "#333",
            fontSize: "0.82rem",
            fontWeight: 500,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            maxWidth: "16em",
          }}
          title={f.rel_path}
        >
          {leaf.name}
        </span>
        <span style={{ color: MUTED, fontSize: "0.74rem" }}>{formatBytes(f.size_bytes)}</span>
        <span style={{ color: MUTED, fontSize: "0.74rem" }}>indexed {formatWhen(f.indexed_at)}</span>
        {f.document_id && (
          <button
            data-testid="file-document"
            type="button"
            onClick={() => copyDocId(f.document_id as string)}
            title={`Indexed as document ${f.document_id} (click to copy id)`}
            aria-label={`Copy document id ${f.document_id}`}
            style={{
              border: "1px solid #ddd",
              borderRadius: 5,
              background: "none",
              color: "#4a90d9",
              fontSize: "0.72rem",
              padding: "0 0.35rem",
              cursor: "pointer",
            }}
          >
            Document
          </button>
        )}
      </div>
      {f.status === "error" && (f.error_code || f.error_detail) && (
        <div data-testid="file-error" style={{ color: RED, fontSize: "0.74rem", paddingLeft: "0.2rem" }}>
          {f.error_code ? <strong style={{ fontWeight: 600 }}>{f.error_code}</strong> : null}
          {f.error_code && f.error_detail ? " — " : null}
          {f.error_detail}
        </div>
      )}
    </li>
  );
}

interface NodesProps {
  nodes: TreeNode[];
  depth: number;
  isOpen: (path: string) => boolean;
  onToggle: (path: string) => void;
}

function TreeNodes({ nodes, depth, isOpen, onToggle }: NodesProps): React.ReactElement {
  return (
    <ul style={{ margin: 0, padding: 0 }}>
      {nodes.map((node) =>
        node.kind === "file" ? (
          <FileRow key={node.path} leaf={node} depth={depth} />
        ) : (
          <li key={node.path} data-testid="dir-node" data-dir-path={node.path} style={{ listStyle: "none" }}>
            <button
              data-testid="dir-toggle"
              type="button"
              aria-expanded={isOpen(node.path)}
              onClick={() => onToggle(node.path)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "0.4rem",
                width: "100%",
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: "0.2rem 0",
                paddingLeft: `${depth * 1.1 + 0.2}rem`,
                textAlign: "left",
                font: "inherit",
              }}
            >
              <span aria-hidden style={{ color: MUTED, fontSize: "0.72rem", width: "0.8em" }}>
                {isOpen(node.path) ? "▾" : "▸"}
              </span>
              <span style={{ fontWeight: 600, fontSize: "0.82rem" }}>{node.name}</span>
              <span style={{ marginLeft: "0.4rem" }}>
                <StatusRollup counts={dirCounts(node)} testid="dir-rollup" emptyText="empty" />
              </span>
            </button>
            {isOpen(node.path) && (
              <TreeNodes nodes={node.children} depth={depth + 1} isOpen={isOpen} onToggle={onToggle} />
            )}
          </li>
        ),
      )}
    </ul>
  );
}

/** A collapsible directory tree built client-side from the loaded files' rel_paths. Directories are
 * `aria-expanded` toggles that show a rollup of their descendants' statuses; leaves are file rows.
 * Open state is remembered per directory; when `expandAll` is set (a filter/search is active) every
 * directory is shown open so the narrowed matches are visible. */
export function FolderFileTree({
  files,
  expandAll = false,
}: {
  files: FolderFileOut[];
  expandAll?: boolean;
}): React.ReactElement {
  const [openDirs, setOpenDirs] = useState<Set<string>>(new Set());

  const tree = buildFileTree(files);
  const isOpen = (path: string): boolean => expandAll || openDirs.has(path);
  const onToggle = (path: string): void =>
    setOpenDirs((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  if (files.length === 0) {
    return (
      <p data-testid="file-tree-empty" style={{ color: MUTED, fontSize: "0.82rem", margin: "0.4rem 0" }}>
        No files match.
      </p>
    );
  }

  return (
    <div data-testid="file-tree">
      <TreeNodes nodes={tree} depth={0} isOpen={isOpen} onToggle={onToggle} />
    </div>
  );
}
