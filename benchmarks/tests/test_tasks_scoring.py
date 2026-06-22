"""Task loading + scorers (no network, no model)."""

from __future__ import annotations

from pathlib import Path

import pytest
from personalai_benchmarks.scoring import exact, includes, model_graded, regex, score_task
from personalai_benchmarks.tasks import Task, load_tasks

_TASKS_DIR = Path(__file__).resolve().parents[1] / "tasks"


def _task(**kw: object) -> Task:
    base = {"id": "t", "category": "reasoning", "capability_tier": "raw", "input": []}
    return Task.model_validate({**base, **kw})


def test_loads_shipped_tasks_with_unique_ids() -> None:
    tasks = load_tasks(_TASKS_DIR)
    assert len(tasks) >= 6
    assert len({t.id for t in tasks}) == len(tasks)  # no duplicates
    assert {"reasoning", "tool_use"} <= {t.category for t in tasks}


def test_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text(
        "- {id: dup, category: x, capability_tier: raw, input: [], expected: '1'}\n"
        "- {id: dup, category: x, capability_tier: raw, input: [], expected: '2'}\n"
    )
    with pytest.raises(ValueError, match="duplicate task ids"):
        load_tasks(tmp_path)


def test_as_messages_roundtrips_roles() -> None:
    t = _task(input=[{"role": "user", "content": "hi"}])
    assert t.as_messages() == [{"role": "user", "content": "hi"}]


def test_programmatic_scorers() -> None:
    assert exact("62", " 62 ").passed
    assert not exact("62", "63").passed
    assert includes("the answer is 62.", "62").passed
    assert includes("FOO", "foo").passed  # case-insensitive by default
    assert regex("result: 62", r"\b62\b").passed
    assert not regex("result: 620", r"\b62\b").passed


def test_score_task_dispatch_and_model_graded() -> None:
    # expected + match=exact -> programmatic
    assert score_task(_task(expected="62", metadata={"match": "exact"}), "62").passed
    # rubric -> model-graded via injected judge
    rubric_task = _task(rubric={"type": "model_graded", "criteria": "mentions Paris"})
    assert score_task(rubric_task, "It's Paris.", judge=lambda a, c: (True, "ok")).passed
    # model-graded with no judge fails closed
    assert not score_task(rubric_task, "Paris").passed
    # neither expected nor rubric
    assert not score_task(_task(), "anything").passed


def test_model_graded_uses_judge_explanation() -> None:
    s = model_graded("ans", "crit", judge=lambda a, c: (False, "missing X"))
    assert not s.passed and s.explanation == "missing X" and s.scorer == "model_graded"
