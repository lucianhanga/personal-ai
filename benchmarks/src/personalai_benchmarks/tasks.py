"""Benchmark task definitions + a YAML loader.

A task is a declarative unit (input + how to grade it), independent of any model/provider — the same
task runs against any system-under-test. Tasks live in ``benchmarks/tasks/*.yaml`` (one or a list
per file) and are versioned by the ``version`` field + git.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class Message(BaseModel):
    """One chat message of a task's input."""

    role: str
    content: str


class Task(BaseModel):
    """A single benchmark task.

    Grading: set ``expected`` for a programmatic match (the match kind comes from
    ``metadata.match`` = "includes" (default) | "exact" | "regex"), or ``rubric`` =
    ``{"type": "model_graded", "criteria": "..."}`` for an LLM-judge.
    """

    id: str
    category: str  # reasoning | knowledge | tool_use | mcp | internet | coding | ...
    capability_tier: str  # informational label: raw | tools | tools_memory | multi_agent
    input: list[Message]
    expected: str | None = None
    rubric: dict[str, Any] | None = None
    version: str = "v1"
    metadata: dict[str, Any] = Field(default_factory=dict)

    def as_messages(self) -> list[dict[str, str]]:
        return [{"role": m.role, "content": m.content} for m in self.input]


def load_tasks(directory: str | Path) -> list[Task]:
    """Load every task from ``*.yaml`` under ``directory`` (each file holds one task or a list)."""
    path = Path(directory)
    if not path.is_dir():
        raise FileNotFoundError(f"tasks directory not found: {path}")
    tasks: list[Task] = []
    for file in sorted(path.glob("*.yaml")):
        raw = yaml.safe_load(file.read_text())
        items = raw if isinstance(raw, list) else [raw]
        for item in items:
            tasks.append(Task.model_validate(item))
    ids = [t.id for t in tasks]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate task ids: {sorted(duplicates)}")
    return tasks
