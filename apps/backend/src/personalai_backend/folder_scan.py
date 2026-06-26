"""Filesystem walk + security boundary for folder-source sync (#456).

Pure and store-free: enumerates the indexable files under a granted folder root while enforcing the
security boundary the design requires. Every yielded path is **contained** in the realpath-resolved
root (no ``..`` or symlink escape), is a **supported type**, is **within the size cap**, and is not
**excluded** by a glob (secrets/VCS/deps ignored by default). Isolating this here makes the security
rules unit-testable with no DB and no watcher — it is the ONLY place the local filesystem is read.

The sync worker re-checks containment again before reading bytes (defense in depth), but a path that
escapes the root never even leaves this iterator.
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# Mirrors personalai_modality_files.parse_document's supported types (txt/md/pdf/docx). Kept in sync
# deliberately — an unsupported file is skipped at scan time, never queued for a doomed parse.
SUPPORTED_EXTS = frozenset({".txt", ".md", ".markdown", ".pdf", ".docx"})

# Directory NAMES pruned wholesale (never descended): VCS, dependency, and cache trees.
EXCLUDE_DIR_NAMES = frozenset(
    {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__"}
)

# Default file exclude globs: never index secrets or editor/atomic-save temp files. Matched against
# both the POSIX rel-path and the bare filename. Caller globs are added on top.
DEFAULT_EXCLUDE_GLOBS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ed25519*",
    "*.p12",
    "*.pfx",
    "*.tmp",
    "*.swp",
    "*~",
    ".#*",
    "~$*",
    "*.crdownload",
    "*.part",
)

# Per-file size cap (a scanned PDF embeds slowly; an unbounded file would stall the worker).
DEFAULT_MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB


@dataclass(frozen=True)
class ScanEntry:
    """One indexable file found under a root: its POSIX path relative to the root + the fast-path
    fingerprint (size + mtime in nanoseconds) the scanner stamps without reading the bytes."""

    rel_path: str
    size_bytes: int
    mtime_ns: int


def canonical_root(root_path: str) -> Path:
    """Resolve a granted root to an absolute, symlink-free path. Raises if it is not an existing dir
    (``FileNotFoundError``/``NotADirectoryError``) — the API turns these into E_FOLDER_NOT_FOUND."""
    resolved = Path(root_path).resolve(strict=True)
    if not resolved.is_dir():
        raise NotADirectoryError(root_path)
    return resolved


def is_contained(path: Path, root: Path) -> bool:
    """True iff ``path`` resolves to ``root`` itself or somewhere beneath it — defeats ``..`` and
    symlink escape, since both sides are realpath-resolved before the comparison."""
    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError):  # pragma: no cover - defensive (loops, bad mounts)
        return False
    return resolved == root or root in resolved.parents


def _matches(rel_posix: str, globs: tuple[str, ...]) -> bool:
    name = rel_posix.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(rel_posix, g) or fnmatch.fnmatch(name, g) for g in globs)


def iter_indexable_files(
    root_path: str,
    *,
    recursive: bool = True,
    include_globs: tuple[str, ...] = (),
    exclude_globs: tuple[str, ...] = (),
    max_file_bytes: int | None = DEFAULT_MAX_FILE_BYTES,
    follow_symlinks: bool = False,
) -> Iterator[ScanEntry]:
    """Yield every indexable :class:`ScanEntry` under ``root_path`` in a single walk, enforcing the
    security + filter rules. Unreadable files are skipped (not raised). Order is os.walk order."""
    root = canonical_root(root_path)
    excludes = DEFAULT_EXCLUDE_GLOBS + tuple(exclude_globs)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        # Prune excluded / escaping / symlinked dirs in place so os.walk never descends them.
        kept: list[str] = []
        for d in dirnames:
            if d in EXCLUDE_DIR_NAMES:
                continue
            child = Path(dirpath) / d
            if not follow_symlinks and child.is_symlink():
                continue
            if not is_contained(child, root):
                continue
            kept.append(d)
        dirnames[:] = kept if recursive else []

        for fname in filenames:
            if Path(fname).suffix.lower() not in SUPPORTED_EXTS:
                continue
            fp = Path(dirpath) / fname
            if not follow_symlinks and fp.is_symlink():
                continue
            if not is_contained(fp, root):
                continue
            rel = fp.relative_to(root).as_posix()
            if _matches(rel, excludes):
                continue
            if include_globs and not _matches(rel, include_globs):
                continue
            try:
                st = fp.stat()
            except OSError:
                continue  # vanished/locked between walk and stat — next scan picks it up
            if max_file_bytes is not None and st.st_size > max_file_bytes:
                continue
            yield ScanEntry(rel_path=rel, size_bytes=st.st_size, mtime_ns=st.st_mtime_ns)
