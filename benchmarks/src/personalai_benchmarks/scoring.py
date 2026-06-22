"""Pluggable scorers. Each returns a :class:`Score` and records its name + params for replay.

Programmatic: ``exact`` / ``includes`` / ``regex``. LLM-judge: ``model_graded`` (the judge call is
injected, so tests need no model). ``score_task`` dispatches on a task's ``expected`` / ``rubric``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from personalai_benchmarks.tasks import Task

# A judge answers "does this response satisfy the criteria?" -> (passed, explanation). Injected so
# the harness can use any model (typically a frontier model) without coupling the scorer to it.
Judge = Callable[[str, str], "tuple[bool, str]"]


@dataclass(frozen=True)
class Score:
    """A graded result. ``value`` in [0,1]; ``passed`` is the boolean outcome."""

    value: float
    passed: bool
    explanation: str
    scorer: str = ""
    params: Mapping[str, Any] = field(default_factory=dict)


def exact(answer: str, expected: str) -> Score:
    ok = answer.strip() == expected.strip()
    return Score(float(ok), ok, f"exact match: {ok}", "exact", {"expected": expected})


def includes(answer: str, expected: str, *, case_sensitive: bool = False) -> Score:
    hay, needle = (answer, expected) if case_sensitive else (answer.lower(), expected.lower())
    ok = needle.strip() in hay
    return Score(
        float(ok),
        ok,
        f"contains {expected!r}: {ok}",
        "includes",
        {"expected": expected, "case_sensitive": case_sensitive},
    )


def regex(answer: str, pattern: str) -> Score:
    ok = re.search(pattern, answer) is not None
    return Score(float(ok), ok, f"regex {pattern!r}: {ok}", "regex", {"pattern": pattern})


def model_graded(answer: str, criteria: str, judge: Judge) -> Score:
    passed, explanation = judge(answer, criteria)
    return Score(float(passed), passed, explanation, "model_graded", {"criteria": criteria})


def score_task(task: Task, answer: str, *, judge: Judge | None = None) -> Score:
    """Grade ``answer`` for ``task`` using its rubric (LLM-judge) or ``expected`` (programmatic)."""
    if task.rubric is not None and task.rubric.get("type") == "model_graded":
        criteria = str(task.rubric.get("criteria", ""))
        if judge is None:
            return Score(0.0, False, "no judge provided for a model-graded task", "model_graded")
        return model_graded(answer, criteria, judge)
    if task.expected is not None:
        kind = str(task.metadata.get("match", "includes"))
        if kind == "exact":
            return exact(answer, task.expected)
        if kind == "regex":
            return regex(answer, task.expected)
        return includes(answer, task.expected)
    return Score(0.0, False, "task has neither expected nor rubric", "none")
