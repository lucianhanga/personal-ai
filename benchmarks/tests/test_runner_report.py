"""Runner + report against a fake in-process system-under-test (no HTTP, no model)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from personalai_benchmarks.adapters import RunResult
from personalai_benchmarks.modes import ALL_MODES, MULTI_TOOLS_MCP, SINGLE_NO_TOOLS, with_memory
from personalai_benchmarks.report import cells, to_markdown, write_report
from personalai_benchmarks.runner import run_suite
from personalai_benchmarks.tasks import Task


class _FakeSUT:
    """Returns a fixed answer; echoes the mode's use_tools into a fake tool_call + config_used."""

    name = "fake"

    def __init__(self, answer: str = "62", error: str | None = None) -> None:
        self._answer = answer
        self._error = error

    def run(self, messages: Sequence[Mapping[str, str]], overrides: Mapping[str, Any]) -> RunResult:
        if self._error is not None:
            return RunResult(error=self._error)
        return RunResult(
            answer=self._answer,
            latency_ms=12.0,
            tool_calls=[{"tool": "calculator"}] if overrides.get("use_tools") else [],
            config_used=dict(overrides),
        )


class _FlakySUT:
    """Cycles through a list of answers, so repeated attempts at one cell pass/fail differently."""

    name = "flaky"

    def __init__(self, answers: list[str]) -> None:
        self._answers = answers
        self._i = 0

    def run(self, messages: Sequence[Mapping[str, str]], overrides: Mapping[str, Any]) -> RunResult:
        ans = self._answers[self._i % len(self._answers)]
        self._i += 1
        return RunResult(answer=ans, latency_ms=5.0)


def _task(tid: str = "t1", expected: str = "62") -> Task:
    return Task.model_validate(
        {
            "id": tid,
            "category": "reasoning",
            "capability_tier": "raw",
            "input": [{"role": "user", "content": "2+2?"}],
            "expected": expected,
        }
    )


def test_memory_axis_is_a_distinct_tier() -> None:
    base = MULTI_TOOLS_MCP
    mem = with_memory(base)
    assert mem.overrides["use_memory"] is True and mem.overrides["memory_enabled"] is True
    assert mem.capability_tier == f"{base.capability_tier}+memory"  # never averaged with memory-off
    assert "multi_tools_mcp_memory" in ALL_MODES


def test_run_suite_scores_and_records_metadata() -> None:
    suite = run_suite(
        tasks=[_task(expected="62"), _task("t2", expected="99")],
        modes=[SINGLE_NO_TOOLS],
        sut=_FakeSUT(answer="62"),
    )
    assert len(suite.records) == 2
    passed = {r.task_id: r.passed for r in suite.records}
    assert passed == {"t1": True, "t2": False}  # t2 expected 99, got 62
    assert suite.metadata["sut"] == "fake" and suite.metadata["git_commit"]
    assert suite.records[0].latency_ms == 12.0


def test_run_suite_records_errors_without_raising() -> None:
    suite = run_suite(tasks=[_task()], modes=[SINGLE_NO_TOOLS], sut=_FakeSUT(error="backend down"))
    r = suite.records[0]
    assert not r.passed and r.error == "backend down" and "run error" in r.explanation


def test_report_groups_by_tier_and_writes_files(tmp_path: Path) -> None:
    suite = run_suite(
        tasks=[_task()],
        modes=[SINGLE_NO_TOOLS, with_memory(MULTI_TOOLS_MCP)],
        sut=_FakeSUT(answer="62"),
    )
    md = to_markdown(suite)
    assert "Leaderboard by capability tier" in md
    assert "single_no_tools" in md and "multi_agent+memory" in md  # tiers shown separately
    assert "Per-task results" in md

    json_path, md_path = write_report(suite, tmp_path)
    assert json_path.exists() and md_path.exists()
    payload = json.loads(json_path.read_text())  # Any -> indexable in the test
    assert payload["metadata"]["sut"] == "fake"
    assert len(payload["records"]) == 2
    assert payload["records"][0]["task_id"] == "t1"


def test_repeats_runs_each_cell_n_times() -> None:
    suite = run_suite(
        tasks=[_task()], modes=[SINGLE_NO_TOOLS], sut=_FakeSUT(answer="62"), repeats=3
    )
    assert len(suite.records) == 3  # one task × one mode × 3 attempts
    assert sorted(r.attempt for r in suite.records) == [0, 1, 2]
    assert suite.metadata["repeats"] == 3


def test_pass_at_k_vs_pass_rate_on_a_flaky_cell() -> None:
    # Expected "62"; attempts answer 62 / 99 / 62 -> 2 of 3 pass.
    suite = run_suite(
        tasks=[_task(expected="62")],
        modes=[SINGLE_NO_TOOLS],
        sut=_FlakySUT(["62", "99", "62"]),
        repeats=3,
    )
    (cell,) = cells(suite)
    assert cell.n == 3
    assert cell.passes == 2
    assert cell.pass_at_k is True  # at least one attempt passed
    assert cell.pass_rate == 2 / 3  # reliability

    md = to_markdown(suite)
    assert "pass@k" in md and "repeats: 3" in md
    assert "2/3" in md  # the per-task cell / pass counts
    assert "Flaky (passed some attempts, not all)" in md  # 2/3 -> flaky section


def test_never_passing_cell_is_a_hard_failure() -> None:
    suite = run_suite(
        tasks=[_task(expected="62")],
        modes=[SINGLE_NO_TOOLS],
        sut=_FakeSUT(answer="99"),  # never matches
        repeats=2,
    )
    (cell,) = cells(suite)
    assert cell.pass_at_k is False and cell.passes == 0
    assert "Failures (never passed)" in to_markdown(suite)
