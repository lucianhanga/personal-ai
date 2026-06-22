"""Runner + report against a fake in-process system-under-test (no HTTP, no model)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from personalai_benchmarks.adapters import RunResult
from personalai_benchmarks.modes import ALL_MODES, MULTI_TOOLS_MCP, SINGLE_NO_TOOLS, with_memory
from personalai_benchmarks.report import cells, to_html, to_markdown, write_report
from personalai_benchmarks.runner import run_comparison, run_suite
from personalai_benchmarks.tasks import Task


class _FakeSUT:
    """Returns a fixed answer; echoes the mode's use_tools into a fake tool_call + config_used."""

    def __init__(self, answer: str = "62", error: str | None = None, name: str = "fake") -> None:
        self.name = name
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

    json_path, md_path, html_path = write_report(suite, tmp_path)
    assert json_path.exists() and md_path.exists() and html_path.exists()
    html_text = html_path.read_text()
    assert html_text.startswith("<!doctype html>") and "leaderboard" in html_text.lower()
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


def test_run_comparison_tags_and_separates_systems() -> None:
    # Two systems answer the same task differently; their cells must not be merged.
    suite = run_comparison(
        tasks=[_task(expected="62")],
        modes=[SINGLE_NO_TOOLS],
        systems=[_FakeSUT(answer="62", name="local"), _FakeSUT(answer="99", name="frontier:x")],
    )
    assert {r.system for r in suite.records} == {"local", "frontier:x"}
    assert suite.metadata["systems"] == ["local", "frontier:x"]
    by_system = {c.system: c for c in cells(suite)}
    assert by_system["local"].pass_at_k is True  # answered 62 (correct)
    assert by_system["frontier:x"].pass_at_k is False  # answered 99
    md = to_markdown(suite)
    assert "local/single_no_tools" in md and "frontier:x/single_no_tools" in md


def test_comparison_grader_receives_the_system_name() -> None:
    seen: list[str] = []

    def grader(task, answer, system_name):  # type: ignore[no-untyped-def]
        from personalai_benchmarks.scoring import Score

        seen.append(system_name)
        return Score(1.0, True, "graded", "stub")

    run_comparison(
        tasks=[_task()],
        modes=[SINGLE_NO_TOOLS],
        systems=[_FakeSUT(name="a"), _FakeSUT(name="b")],
        grader=grader,
    )
    assert set(seen) == {"a", "b"}  # the grader can route by system (self-preference)


def test_on_progress_fires_start_and_result_per_attempt() -> None:
    events: list[tuple[str, str | None]] = []
    run_suite(
        tasks=[_task(expected="62")],
        modes=[SINGLE_NO_TOOLS],
        sut=_FakeSUT(answer="62"),
        repeats=2,
        on_progress=lambda label, result: events.append((label, result)),
    )
    # 2 attempts × (start, result) = 4 callbacks.
    starts = [e for e in events if e[1] is None]
    results = [e for e in events if e[1] is not None]
    assert len(starts) == 2 and len(results) == 2
    assert all("fake · single_no_tools · t1" in label for label, _ in events)
    assert all(r is not None and r.startswith("ok (") for _, r in events if r is not None)


class _UsageSUT:
    """Returns a fixed answer + token usage, so cost/speed columns can be computed."""

    def __init__(self, name: str, usage: dict[str, int]) -> None:
        self.name = name
        self._usage = usage

    def run(self, messages: Sequence[Mapping[str, str]], overrides: Mapping[str, Any]) -> RunResult:
        return RunResult(answer="62", latency_ms=1000.0, usage=self._usage)


def test_leaderboard_has_cost_and_speed_columns() -> None:
    suite = run_comparison(
        tasks=[_task(expected="62")],
        modes=[SINGLE_NO_TOOLS],
        systems=[
            _UsageSUT("openai:gpt-4o", {"prompt_tokens": 1000, "completion_tokens": 500}),
            _UsageSUT("personalia", {"completion_tokens": 500}),
            _UsageSUT("xai:unknown-model", {"completion_tokens": 500}),
        ],
    )
    md = to_markdown(suite)
    assert "$ / run" in md and "tok/s" in md
    assert "$0.0075" in md  # gpt-4o: 1000*2.5/1e6 + 500*10/1e6
    assert "$0.0000" in md  # local PersonalAI is free
    assert "| — |" in md  # unpriced model -> em dash, not a guessed cost
    assert "500" in md  # 500 completion tokens / 1s = 500 tok/s
    assert "$ / run" in to_html(suite) and "tok/s" in to_html(suite)


def test_unicode_bar_scales_to_fraction() -> None:
    from personalai_benchmarks.report import _unicode_bar

    assert _unicode_bar(1.0, width=10) == "█" * 10
    assert _unicode_bar(0.0, width=10) == "░" * 10
    half = _unicode_bar(0.5, width=10)
    assert half.count("█") == 5 and half.count("░") == 5
    # out-of-range fractions are clamped, not crashy
    assert _unicode_bar(2.0, width=4) == "████" and _unicode_bar(-1.0, width=4) == "░░░░"


def test_delta_mark_flags_leader_and_gap() -> None:
    from personalai_benchmarks.report import _delta_mark

    assert _delta_mark(0.9, 0.9) == "best"  # the leader
    assert _delta_mark(0.7, 0.9) == "-0.20"  # signed gap to the leader


def test_leaderboard_renders_bars_and_comparison_marks() -> None:
    # Two systems with different quality -> a ranked tier with a clear best and a laggard.
    suite = run_comparison(
        tasks=[_task(expected="62")],
        modes=[SINGLE_NO_TOOLS],
        systems=[_FakeSUT(answer="62", name="good"), _FakeSUT(answer="0", name="bad")],
    )
    md = to_markdown(suite)
    assert "quality" in md and "Δ best" in md
    assert "best" in md  # the leader is marked
    assert "█" in md  # text bar present

    html_text = to_html(suite)
    assert "barfill" in html_text  # inline score bar in the table
    assert 'class=chart' in html_text and "crow" in html_text  # the per-tier bar chart
    assert "<span class=best>best</span>" in html_text  # leader comparison mark
