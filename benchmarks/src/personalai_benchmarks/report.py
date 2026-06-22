"""Render a :class:`Suite` to a JSON bundle + a Markdown leaderboard.

Fairness rule baked in: results are grouped by ``capability_tier`` and never averaged across tiers,
so a tool-equipped or multi-agent run is never compared head-to-head with a raw single-agent run.
With ``repeats`` > 1 each (task, mode) cell has several attempts; they reduce to **pass@k** (did any
attempt pass — capability) and **pass-rate** (how reliably — passed/N), so stochastic models don't
produce a misleading single-sample pass/FAIL. A per-task matrix + failures list give the drill-down.
"""

from __future__ import annotations

import dataclasses
import json
from collections import defaultdict
from pathlib import Path

from personalai_benchmarks.runner import RunRecord, Suite


@dataclasses.dataclass(frozen=True)
class Cell:
    """The attempts at one (system, mode, task), reduced to pass@k + pass-rate."""

    system: str
    mode: str
    task_id: str
    category: str
    capability_tier: str
    attempts: list[RunRecord]

    @property
    def series(self) -> str:
        """The system+mode identity used as a leaderboard row / matrix column."""
        return f"{self.system}/{self.mode}" if self.system else self.mode

    @property
    def n(self) -> int:
        return len(self.attempts)

    @property
    def passes(self) -> int:
        return sum(1 for r in self.attempts if r.passed)

    @property
    def pass_at_k(self) -> bool:
        return any(r.passed for r in self.attempts)

    @property
    def pass_rate(self) -> float:
        return self.passes / self.n if self.n else 0.0

    @property
    def mean_score(self) -> float:
        return _mean([r.score for r in self.attempts])

    @property
    def mean_latency(self) -> float:
        return _mean([r.latency_ms for r in self.attempts])

    @property
    def explanation(self) -> str:
        # A representative reason a non-passing cell didn't pass (last failed attempt).
        for r in reversed(self.attempts):
            if not r.passed:
                return r.error or r.explanation
        return ""


def cells(suite: Suite) -> list[Cell]:
    """Group the flat attempt records into (system, mode, task) cells."""
    grouped: dict[tuple[str, str, str], list[RunRecord]] = defaultdict(list)
    meta: dict[tuple[str, str, str], RunRecord] = {}
    for r in suite.records:
        key = (r.system, r.mode, r.task_id)
        grouped[key].append(r)
        meta[key] = r
    out: list[Cell] = []
    for key, attempts in grouped.items():
        ref = meta[key]
        out.append(
            Cell(
                system=ref.system,
                mode=ref.mode,
                task_id=ref.task_id,
                category=ref.category,
                capability_tier=ref.capability_tier,
                attempts=attempts,
            )
        )
    return out


def to_json(suite: Suite) -> dict[str, object]:
    return {
        "metadata": suite.metadata,
        "records": [dataclasses.asdict(r) for r in suite.records],
    }


def write_json(suite: Suite, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(to_json(suite), indent=2, ensure_ascii=False))
    return p


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def to_markdown(suite: Suite) -> str:
    md: list[str] = ["# PersonalAI benchmark leaderboard", ""]
    meta = suite.metadata
    systems = list(meta.get("systems") or [meta.get("sut", "?")])
    md.append(
        f"- systems: {', '.join(f'`{s}`' for s in systems)} "
        f"· commit: `{str(meta.get('git_commit', '?'))[:12]}` · {meta.get('timestamp', '?')}"
    )
    md.append(f"- platform: {meta.get('platform', '?')} · python {meta.get('python', '?')}")
    repeats = int(meta.get("repeats", 1))
    md.append(
        f"- tasks: {meta.get('task_count', '?')} · modes: {', '.join(meta.get('modes', []))} "
        f"· repeats: {repeats}"
    )
    md.append("")

    cell_list = cells(suite)
    by_tier_series: dict[str, dict[str, list[Cell]]] = defaultdict(lambda: defaultdict(list))
    for c in cell_list:
        by_tier_series[c.capability_tier][c.series].append(c)

    # Leaderboard, grouped by capability tier (never averaged across tiers). Within a tier, each
    # system/mode is a row: pass@k = fraction of tasks any attempt solved; pass-rate = fraction of
    # all attempts that passed; mean score = quality (judge 0–1 or programmatic 0/1).
    md.append("## Leaderboard by capability tier")
    md.append("")
    for tier in sorted(by_tier_series):
        md.append(f"### Tier: `{tier}`")
        md.append("")
        md.append(
            "| system / mode | pass@k | pass rate | mean score | mean latency (ms) | tasks×reps |"
        )
        md.append("|---|---|---|---|---|---|")
        # Rank rows within a tier by quality then pass-rate.
        ranked = sorted(
            by_tier_series[tier].items(),
            key=lambda kv: (-_mean([c.mean_score for c in kv[1]]), kv[0]),
        )
        for series, cs in ranked:
            tasks_solved = sum(1 for c in cs if c.pass_at_k)
            attempts = sum(c.n for c in cs)
            attempt_passes = sum(c.passes for c in cs)
            pk = tasks_solved / len(cs) * 100 if cs else 0.0
            pr = attempt_passes / attempts * 100 if attempts else 0.0
            md.append(
                f"| {series} | {tasks_solved}/{len(cs)} ({pk:.0f}%) | "
                f"{attempt_passes}/{attempts} ({pr:.0f}%) | "
                f"{_mean([c.mean_score for c in cs]):.2f} | "
                f"{_mean([c.mean_latency for c in cs]):.0f} | {len(cs)}×{repeats} |"
            )
        md.append("")

    # Per-task matrix (task x system/mode -> passes/N), for drill-down.
    series_cols = sorted({c.series for c in cell_list})
    by_task: dict[str, dict[str, Cell]] = defaultdict(dict)
    cat: dict[str, str] = {}
    for c in cell_list:
        by_task[c.task_id][c.series] = c
        cat[c.task_id] = c.category
    md.append("## Per-task results (passes / attempts)")
    md.append("")
    md.append("| task | category | " + " | ".join(series_cols) + " |")
    md.append("|---|---|" + "|".join(["---"] * len(series_cols)) + "|")
    for task_id in sorted(by_task):
        row = []
        for series in series_cols:
            cell = by_task[task_id].get(series)
            row.append("—" if cell is None else f"{cell.passes}/{cell.n}")
        md.append(f"| {task_id} | {cat[task_id]} | " + " | ".join(row) + " |")
    md.append("")

    # Hard failures (never passed any attempt) and flaky cells (passed some, not all).
    hard = [c for c in cell_list if not c.pass_at_k]
    flaky = [c for c in cell_list if c.pass_at_k and c.pass_rate < 1.0]
    if hard:
        md.append("## Failures (never passed)")
        md.append("")
        for c in sorted(hard, key=lambda c: (c.task_id, c.series)):
            md.append(f"- `{c.task_id}` / `{c.series}` ({c.passes}/{c.n}) — {c.explanation}")
        md.append("")
    if flaky:
        md.append("## Flaky (passed some attempts, not all)")
        md.append("")
        for c in sorted(flaky, key=lambda c: (c.task_id, c.series)):
            md.append(f"- `{c.task_id}` / `{c.series}` — {c.passes}/{c.n} passed")
        md.append("")
    return "\n".join(md)


def write_markdown(suite: Suite, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(to_markdown(suite))
    return p


def write_report(suite: Suite, out_dir: str | Path) -> tuple[Path, Path]:
    """Write both ``results.json`` and ``leaderboard.md`` under ``out_dir``; return their paths."""
    out = Path(out_dir)
    return write_json(suite, out / "results.json"), write_markdown(suite, out / "leaderboard.md")
