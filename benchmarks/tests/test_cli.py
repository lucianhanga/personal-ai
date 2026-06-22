"""CLI surface: list-modes, task subsetting, and graceful errors (no backend needed)."""

from __future__ import annotations

from pathlib import Path

from personalai_benchmarks import cli


def test_list_modes(capsys) -> None:  # type: ignore[no-untyped-def]
    assert cli.main(["list-modes"]) == 0
    out = capsys.readouterr().out
    assert "single_no_tools" in out and "multi_tools_mcp_memory" in out


def test_run_unknown_mode_errors(tmp_path: Path) -> None:
    (tmp_path / "t.yaml").write_text(
        "- {id: t, category: reasoning, capability_tier: raw, input: [], expected: '1'}\n"
    )
    assert cli.main(["run", "--tasks", str(tmp_path), "--modes", "does_not_exist"]) == 2


def test_run_missing_tasks_dir_errors() -> None:
    assert cli.main(["run", "--tasks", "/no/such/dir"]) == 2
