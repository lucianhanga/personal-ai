"""Render a :class:`Suite` to a JSON bundle + a Markdown leaderboard.

Fairness rule baked in: results are grouped by ``capability_tier`` and never averaged across tiers,
so a tool-equipped or multi-agent run is never compared head-to-head with a raw single-agent run.
With ``repeats`` > 1 each (task, mode) cell has several attempts; they reduce to **pass@k** (did any
attempt pass — capability) and **pass-rate** (how reliably — passed/N), so stochastic models don't
produce a misleading single-sample pass/FAIL. A per-task matrix + failures list give the drill-down.
"""

from __future__ import annotations

import dataclasses
import html
import json
from collections import defaultdict
from pathlib import Path

from personalai_benchmarks import pricing
from personalai_benchmarks.analysis import length_bias
from personalai_benchmarks.runner import RunRecord, Suite


def _mean_opt(values: list[float | None]) -> float | None:
    """Mean of the non-None values, or None if there are none (so unpriced rows stay '—')."""
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


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
    def mean_cost(self) -> float | None:
        return _mean_opt([pricing.cost_usd(r.system, r.usage) for r in self.attempts])

    @property
    def mean_speed(self) -> float | None:
        return _mean_opt([pricing.tokens_per_sec(r.usage, r.latency_ms) for r in self.attempts])

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


def _fmt_cost(value: float | None) -> str:
    return "—" if value is None else (f"${value:.4f}" if value < 1 else f"${value:.2f}")


def _fmt_speed(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}"


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
    bias = length_bias(suite.records)
    if bias is not None:
        md.append(f"- {bias.summary()}")
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
            "| system / mode | pass@k | pass rate | mean score | latency (ms) | $ / run | tok/s |"
        )
        md.append("|---|---|---|---|---|---|---|")
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
                f"{_mean([c.mean_latency for c in cs]):.0f} | "
                f"{_fmt_cost(_mean_opt([c.mean_cost for c in cs]))} | "
                f"{_fmt_speed(_mean_opt([c.mean_speed for c in cs]))} |"
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


# Color code (matches the app): green = good, amber = middling, red = poor.
_OK, _WARN, _BAD = "#1a7f37", "#b06f00", "#b00020"


def _grade_color(fraction: float) -> str:
    return _OK if fraction >= 0.8 else _WARN if fraction >= 0.5 else _BAD


def to_html(suite: Suite) -> str:
    """A self-contained, styled HTML leaderboard — open in a browser, or print it to PDF."""
    esc = html.escape
    meta = suite.metadata
    systems = list(meta.get("systems") or [meta.get("sut", "?")])
    repeats = int(meta.get("repeats", 1))
    cell_list = cells(suite)
    by_tier_series: dict[str, dict[str, list[Cell]]] = defaultdict(lambda: defaultdict(list))
    for c in cell_list:
        by_tier_series[c.capability_tier][c.series].append(c)

    out: list[str] = [
        "<!doctype html><html lang=en><head><meta charset=utf-8>",
        "<title>PersonalAI benchmark leaderboard</title>",
        "<style>",
        "body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:2rem auto;"
        "max-width:1000px;color:#1a1a1a;padding:0 1rem}",
        "h1{font-size:1.5rem;margin:0 0 .25rem}h2{font-size:1.05rem;margin:1.6rem 0 .4rem}",
        ".meta{color:#555;font-size:.85rem;margin-bottom:1rem}",
        "table{border-collapse:collapse;width:100%;margin:.3rem 0 1rem;font-size:.88rem}",
        "th,td{padding:.4rem .6rem;text-align:left;border-bottom:1px solid #eee}",
        "th{background:#f6f8fa;font-weight:600}tr:hover{background:#fafbfc}",
        ".tier{display:inline-block;padding:.1rem .5rem;border-radius:1rem;background:#eef;"
        "color:#338;font-size:.8rem}",
        ".num{font-variant-numeric:tabular-nums;text-align:right}.bar{font-weight:600}",
        ".rank{color:#888;width:1.5rem}.fail{color:#b00020}.pass{color:#1a7f37}",
        "code{background:#f6f8fa;padding:.05rem .3rem;border-radius:3px;font-size:.85em}",
        "@media print{body{margin:0;max-width:none}h2{page-break-after:avoid}}",
        "</style></head><body>",
        "<h1>PersonalAI benchmark leaderboard</h1>",
        "<div class=meta>",
        f"systems: {', '.join(f'<code>{esc(s)}</code>' for s in systems)}<br>",
        f"commit <code>{esc(str(meta.get('git_commit', '?'))[:12])}</code> · "
        f"{esc(str(meta.get('timestamp', '?')))} · {esc(str(meta.get('platform', '?')))}<br>",
        f"tasks: {meta.get('task_count', '?')} · modes: {esc(', '.join(meta.get('modes', [])))} "
        f"· repeats: {repeats} · judge: {esc(str(meta.get('judge', 'off')))}",
        "</div>",
    ]

    for tier in sorted(by_tier_series):
        out.append(f"<h2>Tier <span class=tier>{esc(tier)}</span></h2>")
        out.append(
            "<table><tr><th class=rank>#</th><th>system / mode</th><th class=num>pass@k</th>"
            "<th class=num>pass rate</th><th class=num>mean score</th>"
            "<th class=num>latency (ms)</th><th class=num>$ / run</th><th class=num>tok/s</th></tr>"
        )
        ranked = sorted(
            by_tier_series[tier].items(),
            key=lambda kv: (-_mean([c.mean_score for c in kv[1]]), kv[0]),
        )
        for i, (series, cs) in enumerate(ranked, 1):
            solved = sum(1 for c in cs if c.pass_at_k)
            attempts = sum(c.n for c in cs)
            passes = sum(c.passes for c in cs)
            mean_score = _mean([c.mean_score for c in cs])
            pr = passes / attempts if attempts else 0.0
            out.append(
                f"<tr><td class=rank>{i}</td><td><code>{esc(series)}</code></td>"
                f"<td class=num>{solved}/{len(cs)}</td>"
                f'<td class="num" style="color:{_grade_color(pr)}">{passes}/{attempts} '
                f"({pr * 100:.0f}%)</td>"
                f'<td class="num bar" style="color:{_grade_color(mean_score)}">'
                f"{mean_score:.2f}</td>"
                f"<td class=num>{_mean([c.mean_latency for c in cs]):.0f}</td>"
                f"<td class=num>{esc(_fmt_cost(_mean_opt([c.mean_cost for c in cs])))}</td>"
                f"<td class=num>{_fmt_speed(_mean_opt([c.mean_speed for c in cs]))}</td></tr>"
            )
        out.append("</table>")

    # Per-task matrix.
    series_cols = sorted({c.series for c in cell_list})
    by_task: dict[str, dict[str, Cell]] = defaultdict(dict)
    cat: dict[str, str] = {}
    for c in cell_list:
        by_task[c.task_id][c.series] = c
        cat[c.task_id] = c.category
    out.append("<h2>Per-task results <small>(passes / attempts)</small></h2><table>")
    out.append(
        "<tr><th>task</th><th>category</th>"
        + "".join(f"<th class=num>{esc(s)}</th>" for s in series_cols)
        + "</tr>"
    )
    for task_id in sorted(by_task):
        cells_html = []
        for s in series_cols:
            cell = by_task[task_id].get(s)
            if cell is None:
                cells_html.append("<td class=num>—</td>")
            else:
                color = _grade_color(cell.pass_rate)
                cells_html.append(
                    f'<td class="num" style="color:{color}">{cell.passes}/{cell.n}</td>'
                )
        out.append(
            f"<tr><td><code>{esc(task_id)}</code></td><td>{esc(cat[task_id])}</td>"
            + "".join(cells_html)
            + "</tr>"
        )
    out.append("</table>")

    hard = [c for c in cell_list if not c.pass_at_k]
    if hard:
        out.append("<h2>Failures (never passed)</h2><ul>")
        for c in sorted(hard, key=lambda c: (c.task_id, c.series)):
            out.append(
                f"<li class=fail><code>{esc(c.task_id)}</code> / <code>{esc(c.series)}</code> "
                f"({c.passes}/{c.n}) — {esc(c.explanation)}</li>"
            )
        out.append("</ul>")
    out.append(
        "<p class=meta>Tip: print this page to PDF from your browser for a shareable report.</p>"
    )
    out.append("</body></html>")
    return "".join(out)


def write_html(suite: Suite, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(to_html(suite))
    return p


def write_report(suite: Suite, out_dir: str | Path) -> tuple[Path, Path, Path]:
    """Write ``results.json`` + ``leaderboard.md`` + ``leaderboard.html``; return their paths."""
    out = Path(out_dir)
    return (
        write_json(suite, out / "results.json"),
        write_markdown(suite, out / "leaderboard.md"),
        write_html(suite, out / "leaderboard.html"),
    )
