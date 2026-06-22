"""Result cache: key stability, round-trip, disable/refresh, persistence (#345)."""

from __future__ import annotations

from pathlib import Path

from personalai_benchmarks.cache import ResultCache, cell_key
from personalai_benchmarks.runner import RunRecord


def _rec(system: str = "openai:gpt-4o", task: str = "t1") -> RunRecord:
    return RunRecord(
        task_id=task,
        category="reasoning",
        mode="raw",
        capability_tier="raw",
        answer="42",
        score=1.0,
        passed=True,
        explanation="ok",
        latency_ms=10.0,
        usage={"completion_tokens": 5},
        tool_calls=[],
        config_used={},
        error=None,
        system=system,
    )


def _key(
    *,
    system: str = "openai:gpt-4o",
    mode: str = "raw",
    task_id: str = "t1",
    task_version: str = "v1",
    fingerprint: str = "exact",
    repeats: int = 1,
) -> str:
    return cell_key(
        system=system,
        mode=mode,
        task_id=task_id,
        task_version=task_version,
        fingerprint=fingerprint,
        repeats=repeats,
    )


def test_cell_key_distinguishes_the_things_that_change_a_result() -> None:
    k = _key()
    assert _key(task_version="v2") != k  # edited task
    assert _key(task_id="t2") != k  # different task
    assert _key(fingerprint="judge:v2") != k  # judged differently
    assert _key(repeats=3) != k  # bigger sample
    assert _key() == k  # stable


def test_put_get_roundtrip(tmp_path: Path) -> None:
    cache = ResultCache.load(tmp_path / "c.json")
    recs = [_rec(), _rec()]
    cache.put("k", recs)
    got = cache.get("k")
    assert got is not None and len(got) == 2
    assert got[0].system == "openai:gpt-4o" and got[0].passed
    assert cache.get("missing") is None


def test_disabled_cache_is_a_noop(tmp_path: Path) -> None:
    cache = ResultCache.load(tmp_path / "c.json", enabled=False)
    cache.put("k", [_rec()])
    assert cache.get("k") is None
    cache.save()
    assert not (tmp_path / "c.json").exists()  # disabled never writes


def test_refresh_ignores_existing_but_still_stores(tmp_path: Path) -> None:
    ResultCache.load(tmp_path / "c.json")  # seed nothing
    cache = ResultCache.load(tmp_path / "c.json", refresh=True)
    cache.put("k", [_rec()])
    assert cache.get("k") is None  # refresh: never a hit, forces a re-run
    assert cache.stored == 1


def test_persists_across_load(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    a = ResultCache.load(path)
    a.put("k", [_rec(task="t9")])
    a.save()
    b = ResultCache.load(path)  # a fresh process would see the stored cell
    got = b.get("k")
    assert got is not None and got[0].task_id == "t9"


def test_corrupt_cache_file_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text("{not json")
    cache = ResultCache.load(path)  # must not raise
    assert cache.get("k") is None
