"""Run tasks x modes against a system-under-test; capture scored records + reproducibility data."""

from __future__ import annotations

import platform
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from personalai_benchmarks.adapters import SystemUnderTest
from personalai_benchmarks.modes import Mode
from personalai_benchmarks.scoring import Judge, Score, score_task
from personalai_benchmarks.tasks import Task


@dataclass(frozen=True)
class RunRecord:
    """One (task, mode) result with its score, trajectory, and cost/latency signals."""

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
) -> Suite:
    """Run every (task, mode) pair through ``sut``, scoring each; errors recorded, not raised."""
    records: list[RunRecord] = []
    for task in tasks:
        for mode in modes:
            result = sut.run(task.as_messages(), mode.overrides)
            if result.error is not None:
                score = Score(0.0, False, f"run error: {result.error}", "error")
            else:
                score = score_task(task, result.answer, judge=judge)
            records.append(
                RunRecord(
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
                )
            )
    metadata = {
        "git_commit": _git_commit(),
        "timestamp": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "sut": sut.name,
        "modes": [m.name for m in modes],
        "task_count": len(tasks),
    }
    return Suite(records=records, metadata=metadata)
