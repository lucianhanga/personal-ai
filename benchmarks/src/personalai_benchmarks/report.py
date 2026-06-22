"""Render a :class:`Suite` to a JSON bundle + a Markdown leaderboard.

Fairness rule baked in: results are grouped by ``capability_tier`` and never averaged across tiers,
so a tool-equipped or multi-agent run is never compared head-to-head with a raw single-agent run.
Each tier shows its modes with pass-rate, mean score, and mean latency (the cost axis grows in
Phase 2). A per-task matrix and a failures list give the drill-down.
"""

from __future__ import annotations

import dataclasses
import json
from collections import defaultdict
from pathlib import Path

from personalai_benchmarks.runner import RunRecord, Suite


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
    md.append(f"- tasks: {meta.get('task_count', '?')} · modes: {', '.join(meta.get('modes', []))}")
    md.append("")

    # Leaderboard, grouped by capability tier (never averaged across tiers).
    by_tier: dict[str, dict[str, list[RunRecord]]] = defaultdict(lambda: defaultdict(list))
    for r in suite.records:
        by_tier[r.capability_tier][r.mode].append(r)

    md.append("## Leaderboard by capability tier")
    md.append("")
    for tier in sorted(by_tier):
        md.append(f"### Tier: `{tier}`")
        md.append("")
        md.append("| mode | pass rate | mean score | mean latency (ms) | n |")
        md.append("|---|---|---|---|---|")
        for mode in sorted(by_tier[tier]):
            recs = by_tier[tier][mode]
            n = len(recs)
            passed = sum(1 for r in recs if r.passed)
            md.append(
                f"| {mode} | {passed}/{n} ({passed / n * 100:.0f}%) | "
                f"{_mean([r.score for r in recs]):.2f} | "
                f"{_mean([r.latency_ms for r in recs]):.0f} | {n} |"
            )
        md.append("")

    # Per-task matrix (task x mode -> pass/fail), for drill-down.
    modes = sorted({r.mode for r in suite.records})
    md.append("## Per-task results")
    md.append("")
    md.append("| task | category | " + " | ".join(modes) + " |")
    md.append("|---|---|" + "|".join(["---"] * len(modes)) + "|")
    by_task: dict[str, dict[str, RunRecord]] = defaultdict(dict)
    cat: dict[str, str] = {}
    for r in suite.records:
        by_task[r.task_id][r.mode] = r
        cat[r.task_id] = r.category
    for task_id in sorted(by_task):
        cells = []
        for mode in modes:
            rec = by_task[task_id].get(mode)
            cells.append("—" if rec is None else ("pass" if rec.passed else "FAIL"))
        md.append(f"| {task_id} | {cat[task_id]} | " + " | ".join(cells) + " |")
    md.append("")

    # Failures, with the grader's explanation/error.
    failures = [r for r in suite.records if not r.passed]
    if failures:
        md.append("## Failures")
        md.append("")
        for r in failures:
            why = r.error or r.explanation
            md.append(f"- `{r.task_id}` / `{r.mode}` — {why}")
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
