"""Run tasks x modes against a system-under-test; capture scored records + reproducibility data."""

from __future__ import annotations

import platform
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from personalai_benchmarks.adapters import SystemUnderTest
from personalai_benchmarks.modes import Mode
from personalai_benchmarks.scoring import Judge, Score, score_task
from personalai_benchmarks.tasks import Task

# A grader scores a task's answer given the system that produced it (so the judge can apply its
# self-preference fallback). Takes precedence over the simple ``judge`` when provided.
Grader = Callable[[Task, str, str], Score]

# Live progress: called as ``(label, result)`` at the start of each attempt (result=None) and again
# with the result string when it finishes, so a CLI can show what is in flight on a long run.
OnProgress = Callable[[str, "str | None"], None]


@dataclass(frozen=True)
class RunRecord:
    """One attempt at a (task, mode) with its score, trajectory, and cost/latency signals.

    A cell may have several attempts (``repeats``); the report aggregates them into pass@k +
    pass-rate. ``attempt`` is the 0-based index within the cell.
    """

    task_id: str
    category: str
    mode: str
    capability_tier: str
    answer: str
    score: float
    passed: bool
    explanation: str
    latency_ms: float
    usage: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    config_used: dict[str, Any]
    error: str | None
    attempt: int = 0
    system: str = ""  # the system-under-test (e.g. "personalia", "openai:gpt-4o")
    scorer: str = ""  # which scorer graded it (e.g. "llm_judge", "includes"); for bias analysis


@dataclass(frozen=True)
class Suite:
    """A full benchmark run: its records plus the metadata needed to reproduce/compare it."""

    records: list[RunRecord]
    metadata: dict[str, Any] = field(default_factory=dict)


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=5
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def run_suite(
    *,
    tasks: Sequence[Task],
    modes: Sequence[Mode],
    sut: SystemUnderTest,
    judge: Judge | None = None,
    grader: Grader | None = None,
    repeats: int = 1,
    on_progress: OnProgress | None = None,
    sink: list[RunRecord] | None = None,
) -> Suite:
    """Run every (task, mode) pair through ``sut`` ``repeats`` times, scoring each attempt; errors
    are recorded, not raised. Each attempt is its own record (the report reduces them to pass@k).
    ``grader`` (system-aware, e.g. the LLM judge) takes precedence over the simple ``judge``.
    ``on_progress`` is called at the start (result=None) and end of each attempt for live output.
    ``sink``: if given, each record is appended to it as produced, so a caller still holds the
    partial results if a :class:`KeyboardInterrupt` unwinds mid-run (Ctrl-C → partial report)."""
    n = max(1, repeats)
    records: list[RunRecord] = []
    for task in tasks:
        for mode in modes:
            for attempt in range(n):
                label = f"{sut.name} · {mode.name} · {task.id}"
                if on_progress is not None:
                    on_progress(label, None)
                result = sut.run(task.as_messages(), mode.overrides)
                if result.error is not None:
                    score = Score(0.0, False, f"run error: {result.error}", "error")
                elif grader is not None:
                    score = grader(task, result.answer, sut.name)
                else:
                    score = score_task(task, result.answer, judge=judge)
                if on_progress is not None:
                    outcome = (
                        f"error: {result.error[:60]}"
                        if result.error is not None
                        else f"{'ok' if score.passed else 'FAIL'} ({result.latency_ms:.0f}ms)"
                    )
                    on_progress(label, outcome)
                record = RunRecord(
                    task_id=task.id,
                    category=task.category,
                    mode=mode.name,
                    capability_tier=mode.capability_tier,
                    answer=result.answer,
                    score=score.value,
                    passed=score.passed,
                    explanation=score.explanation,
                    latency_ms=result.latency_ms,
                    usage=result.usage,
                    tool_calls=result.tool_calls,
                    config_used=result.config_used,
                    error=result.error,
                    attempt=attempt,
                    system=sut.name,
                    scorer=score.scorer,
                )
                records.append(record)
                if sink is not None:
                    sink.append(record)
    metadata = {
        "git_commit": _git_commit(),
        "timestamp": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "sut": sut.name,
        "modes": [m.name for m in modes],
        "task_count": len(tasks),
        "repeats": n,
    }
    return Suite(records=records, metadata=metadata)


def run_comparison(
    *,
    tasks: Sequence[Task],
    modes: Sequence[Mode],
    systems: Sequence[SystemUnderTest],
    grader: Grader | None = None,
    judge: Judge | None = None,
    repeats: int = 1,
    on_progress: OnProgress | None = None,
    sink: list[RunRecord] | None = None,
) -> Suite:
    """Run the same tasks×modes against several systems into one combined, system-tagged suite, so a
    single leaderboard can compare PersonalAI against frontier contestants. ``sink`` (if given)
    accumulates records live across all systems so a Ctrl-C still yields a partial report."""
    records: list[RunRecord] = []
    for system in systems:
        suite = run_suite(
            tasks=tasks,
            modes=modes,
            sut=system,
            judge=judge,
            grader=grader,
            repeats=repeats,
            on_progress=on_progress,
            sink=sink,
        )
        records.extend(suite.records)
    metadata = {
        "git_commit": _git_commit(),
        "timestamp": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "systems": [s.name for s in systems],
        "modes": [m.name for m in modes],
        "task_count": len(tasks),
        "repeats": max(1, repeats),
    }
    return Suite(records=records, metadata=metadata)
