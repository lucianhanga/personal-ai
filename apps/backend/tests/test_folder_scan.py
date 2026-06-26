"""Folder scan + security boundary (#456) — pure, no DB. Exercises the containment, symlink-escape,
glob, size, and type rules with real temp dirs."""

from __future__ import annotations

from pathlib import Path

import pytest

from personalai_backend.folder_scan import (
    canonical_root,
    is_contained,
    iter_indexable_files,
)


def _rels(root: Path, **kw: object) -> set[str]:
    return {e.rel_path for e in iter_indexable_files(str(root), **kw)}  # type: ignore[arg-type]


def test_finds_supported_types_skips_unsupported(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hi")
    (tmp_path / "b.md").write_text("# h")
    (tmp_path / "c.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "d.png").write_bytes(b"\x89PNG")  # unsupported
    (tmp_path / "e.exe").write_bytes(b"MZ")  # unsupported
    assert _rels(tmp_path) == {"a.txt", "b.md", "c.pdf"}


def test_recursive_and_non_recursive(tmp_path: Path) -> None:
    (tmp_path / "top.txt").write_text("x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.txt").write_text("y")
    assert _rels(tmp_path, recursive=True) == {"top.txt", "sub/deep.txt"}
    assert _rels(tmp_path, recursive=False) == {"top.txt"}


def test_default_excludes_secrets_and_temp(tmp_path: Path) -> None:
    (tmp_path / "ok.txt").write_text("x")
    (tmp_path / ".env").write_text("SECRET=1")
    (tmp_path / "server.pem").write_text("-----BEGIN-----")
    (tmp_path / "id_rsa").write_text("key")
    (tmp_path / "note.txt~").write_text("backup")  # editor temp (unsupported ext anyway)
    assert _rels(tmp_path) == {"ok.txt"}


def test_prunes_vcs_and_dependency_dirs(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("x")
    for d in (".git", "node_modules", ".venv", "__pycache__"):
        sub = tmp_path / d
        sub.mkdir()
        (sub / "inside.txt").write_text("nope")
    assert _rels(tmp_path) == {"keep.txt"}


def test_caller_exclude_and_include_globs(tmp_path: Path) -> None:
    (tmp_path / "keep.md").write_text("x")
    (tmp_path / "draft.md").write_text("x")
    assert _rels(tmp_path, exclude_globs=("draft.*",)) == {"keep.md"}
    # include is an allowlist when set.
    (tmp_path / "notes.txt").write_text("x")
    assert _rels(tmp_path, include_globs=("*.md",)) == {"keep.md", "draft.md"}


def test_size_cap(tmp_path: Path) -> None:
    (tmp_path / "small.txt").write_text("x")
    (tmp_path / "big.txt").write_text("y" * 5000)
    assert _rels(tmp_path, max_file_bytes=1000) == {"small.txt"}


def test_symlinked_file_escaping_root_is_not_yielded(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("leak")
    root = tmp_path / "root"
    root.mkdir()
    (root / "real.txt").write_text("ok")
    link = root / "link.txt"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    # Default (follow_symlinks=False): the escaping symlink is skipped, only the real file remains.
    assert _rels(root) == {"real.txt"}


def test_symlinked_dir_escaping_root_is_pruned(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("leak")
    root = tmp_path / "root"
    root.mkdir()
    (root / "real.txt").write_text("ok")
    try:
        (root / "linkdir").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    assert _rels(root) == {"real.txt"}


def test_is_contained_rejects_dotdot_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    assert is_contained(root / "a" / "b.txt", root) is True
    assert is_contained(root / ".." / "evil.txt", root) is False
    assert is_contained(tmp_path / "sibling.txt", root) is False


def test_canonical_root_validates(tmp_path: Path) -> None:
    assert canonical_root(str(tmp_path)) == tmp_path.resolve()
    with pytest.raises(FileNotFoundError):
        canonical_root(str(tmp_path / "missing"))
    f = tmp_path / "file.txt"
    f.write_text("x")
    with pytest.raises(NotADirectoryError):
        canonical_root(str(f))
