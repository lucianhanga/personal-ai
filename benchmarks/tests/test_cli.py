"""CLI surface: list-modes, task subsetting, and graceful errors (no backend needed)."""

from __future__ import annotations

from pathlib import Path

import pytest
from personalai_benchmarks import cli, frontier


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


def test_compare_with_no_systems_returns_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # No frontier keys + PersonalAI skipped -> nothing to run (no network touched).
    for p in frontier.PROVIDERS.values():
        monkeypatch.delenv(p.env_var, raising=False)
    (tmp_path / "t.yaml").write_text(
        "- {id: t, category: reasoning, capability_tier: raw, input: [], expected: '1'}\n"
    )
    rc = cli.main(["compare", "--no-personalia", "--tasks", str(tmp_path)])
    assert rc == 2
    assert "no systems to run" in capsys.readouterr().err
