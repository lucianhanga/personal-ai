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
    """The attempts at one (task, mode), reduced to pass@k + pass-rate."""

    mode: str
    task_id: str
    category: str
    capability_tier: str
    attempts: list[RunRecord]

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
    """Group the flat attempt records into (task, mode) cells."""
    grouped: dict[tuple[str, str], list[RunRecord]] = defaultdict(list)
    meta: dict[tuple[str, str], RunRecord] = {}
    for r in suite.records:
        grouped[(r.mode, r.task_id)].append(r)
        meta[(r.mode, r.task_id)] = r
    out: list[Cell] = []
    for key, attempts in grouped.items():
        ref = meta[key]
        out.append(
            Cell(
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
    md.append(
        f"- system: `{meta.get('sut', '?')}` · commit: `{str(meta.get('git_commit', '?'))[:12]}` "
        f"· {meta.get('timestamp', '?')}"
    )
    md.append(f"- platform: {meta.get('platform', '?')} · python {meta.get('python', '?')}")
    repeats = int(meta.get("repeats", 1))
    md.append(
        f"- tasks: {meta.get('task_count', '?')} · modes: {', '.join(meta.get('modes', []))} "
        f"· repeats: {repeats}"
    )
    md.append("")

    cell_list = cells(suite)
    by_tier_mode: dict[str, dict[str, list[Cell]]] = defaultdict(lambda: defaultdict(list))
    for c in cell_list:
        by_tier_mode[c.capability_tier][c.mode].append(c)

    # Leaderboard, grouped by capability tier (never averaged across tiers). pass@k = fraction of
    # tasks any attempt solved; pass-rate = fraction of all attempts that passed.
    md.append("## Leaderboard by capability tier")
    md.append("")
    for tier in sorted(by_tier_mode):
        md.append(f"### Tier: `{tier}`")
        md.append("")
        md.append("| mode | pass@k | pass rate | mean latency (ms) | tasks×reps |")
        md.append("|---|---|---|---|---|")
        for mode in sorted(by_tier_mode[tier]):
            cs = by_tier_mode[tier][mode]
            tasks_solved = sum(1 for c in cs if c.pass_at_k)
            attempts = sum(c.n for c in cs)
            attempt_passes = sum(c.passes for c in cs)
            pk = tasks_solved / len(cs) * 100 if cs else 0.0
            pr = attempt_passes / attempts * 100 if attempts else 0.0
            md.append(
                f"| {mode} | {tasks_solved}/{len(cs)} ({pk:.0f}%) | "
                f"{attempt_passes}/{attempts} ({pr:.0f}%) | "
                f"{_mean([c.mean_latency for c in cs]):.0f} | {len(cs)}×{repeats} |"
            )
        md.append("")

    # Per-task matrix (task x mode -> passes/N), for drill-down.
    modes = sorted({c.mode for c in cell_list})
    by_task: dict[str, dict[str, Cell]] = defaultdict(dict)
    cat: dict[str, str] = {}
    for c in cell_list:
        by_task[c.task_id][c.mode] = c
        cat[c.task_id] = c.category
    md.append("## Per-task results (passes / attempts)")
    md.append("")
    md.append("| task | category | " + " | ".join(modes) + " |")
    md.append("|---|---|" + "|".join(["---"] * len(modes)) + "|")
    for task_id in sorted(by_task):
        row = []
        for mode in modes:
            cell = by_task[task_id].get(mode)
            row.append("—" if cell is None else f"{cell.passes}/{cell.n}")
        md.append(f"| {task_id} | {cat[task_id]} | " + " | ".join(row) + " |")
    md.append("")

    # Hard failures (never passed any attempt) and flaky cells (passed some, not all).
    hard = [c for c in cell_list if not c.pass_at_k]
    flaky = [c for c in cell_list if c.pass_at_k and c.pass_rate < 1.0]
    if hard:
        md.append("## Failures (never passed)")
        md.append("")
        for c in sorted(hard, key=lambda c: (c.task_id, c.mode)):
            md.append(f"- `{c.task_id}` / `{c.mode}` ({c.passes}/{c.n}) — {c.explanation}")
        md.append("")
    if flaky:
        md.append("## Flaky (passed some attempts, not all)")
        md.append("")
        for c in sorted(flaky, key=lambda c: (c.task_id, c.mode)):
            md.append(f"- `{c.task_id}` / `{c.mode}` — {c.passes}/{c.n} passed")
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
