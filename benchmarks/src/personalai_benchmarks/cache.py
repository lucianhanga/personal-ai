"""A result cache so deterministic frontier results aren't re-run (#345).

Frontier models run at temperature 0, so a ``(model, task)`` result won't change between runs —
caching it skips the API call (and its cost) next time. The **local PersonalAI** system changes
constantly and is NEVER cached; **tool-equipped** frontier runs depend on local tools, so they
aren't cached either. Only the *raw* frontier tier is cached, and the CLI decides that by passing a
cache to just that run.

The cache key folds in the **task version** and a **grading fingerprint**, so editing a task (bump
its ``version``) or changing the judge re-runs that cell, while a brand-new task is simply a miss
and runs. Stored per cell (all ``repeats`` attempts together); the repeat count is part of the key,
so asking for more attempts re-runs rather than returning a smaller sample.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # RunRecord is imported lazily in get() so runner can import this module
    from personalai_benchmarks.runner import RunRecord

_Cells = dict[str, list[dict[str, Any]]]  # serialized RunRecords keyed by cell


def cell_key(
    *, system: str, mode: str, task_id: str, task_version: str, fingerprint: str, repeats: int
) -> str:
    """A stable cache key for one (system, mode, task) cell under a given grading fingerprint."""
    return f"{system}|{mode}|{task_id}|{task_version}|{fingerprint}|r{repeats}"


@dataclass
class ResultCache:
    """A JSON-file cache of per-cell :class:`RunRecord` lists. ``enabled=False`` is a no-op cache;
    ``refresh=True`` ignores existing entries (forces re-run) but still writes fresh ones."""

    path: Path
    enabled: bool = True
    refresh: bool = False
    _data: _Cells = field(default_factory=dict)
    hits: int = 0
    stored: int = 0

    @classmethod
    def load(cls, path: str | Path, *, enabled: bool = True, refresh: bool = False) -> ResultCache:
        p = Path(path)
        data: _Cells = {}
        if enabled and p.exists():
            try:
                loaded = json.loads(p.read_text())
                if isinstance(loaded, dict):
                    data = loaded
            except (ValueError, OSError):
                data = {}  # a corrupt cache is ignored, not fatal
        return cls(path=p, enabled=enabled, refresh=refresh, _data=data)

    def get(self, key: str) -> list[RunRecord] | None:
        """Cached records for ``key``, or None on a miss (or when disabled / refreshing)."""
        if not self.enabled or self.refresh:
            return None
        raw = self._data.get(key)
        if raw is None:
            return None
        from personalai_benchmarks.runner import RunRecord

        self.hits += 1
        return [RunRecord(**r) for r in raw]

    def put(self, key: str, records: list[RunRecord]) -> None:
        if not self.enabled:
            return
        self._data[key] = [dataclasses.asdict(r) for r in records]
        self.stored += 1

    def save(self) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False))
