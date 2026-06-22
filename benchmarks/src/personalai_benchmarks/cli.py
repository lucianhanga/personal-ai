"""Command-line entry point for the benchmark harness.

    python -m personalai_benchmarks run     [--modes …] [--repeats N] …   # PersonalAI only
    python -m personalai_benchmarks compare [--providers …] [--no-judge] …  # PersonalAI vs frontier
    python -m personalai_benchmarks list-modes

``compare`` runs PersonalAI (across its modes) and each frontier model with a key (raw tier) over
the same tasks, grades open-ended tasks with the LLM judge (Claude, GPT fallback for Claude's own
rows), and writes one combined leaderboard. Providers without a key are skipped and reported.
"""

from __future__ import annotations

import argparse
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

from personalai_benchmarks import frontier, frontier_tools
from personalai_benchmarks.adapters import PersonalIAAdapter
from personalai_benchmarks.judge import default_judge
from personalai_benchmarks.modes import ALL_MODES, FRONTIER_TOOLS, RAW
from personalai_benchmarks.report import write_report
from personalai_benchmarks.runner import (
    Grader,
    OnProgress,
    RunRecord,
    Suite,
    _git_commit,
    run_comparison,
    run_suite,
)
from personalai_benchmarks.tasks import Task, load_tasks

_DEFAULT_TASKS = Path(__file__).resolve().parents[2] / "tasks"
_DEFAULT_COMPARE_MODES = "single_no_tools,single_tools_mcp,multi_tools_mcp"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="personalai_benchmarks")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run PersonalAI across modes and write reports")
    _add_common(run, modes_default=",".join(ALL_MODES))

    cmp = sub.add_parser(
        "compare", help="compare PersonalAI vs frontier models (LLM-judge quality)"
    )
    _add_common(cmp, modes_default=_DEFAULT_COMPARE_MODES)
    cmp.add_argument(
        "--providers",
        default="",
        help="comma frontier providers (default: all with a key). "
        f"Known: {', '.join(frontier.PROVIDERS)}",
    )
    cmp.add_argument(
        "--no-personalia", action="store_true", help="skip the local PersonalAI system"
    )
    cmp.add_argument(
        "--frontier-tools",
        action="store_true",
        help="also run each frontier model with PersonalAI's tools (the assistant/'chat' variant)",
    )
    cmp.add_argument("--no-judge", action="store_true", help="skip LLM-judge quality grading")

    sub.add_parser("list-modes", help="list available benchmark modes")

    ui = sub.add_parser("ui", help="open a local web page to configure + run a comparison")
    ui.add_argument("--port", type=int, default=8900, help="port to serve on (default 8900)")
    ui.add_argument(
        "--base-url", default="http://127.0.0.1:8765", help="personalIA backend URL for runs"
    )
    return parser


def _add_common(p: argparse.ArgumentParser, *, modes_default: str) -> None:
    p.add_argument("--tasks", default=str(_DEFAULT_TASKS), help="directory of *.yaml task files")
    p.add_argument(
        "--task-ids", default="", help="comma-separated subset of task ids (default: all)"
    )
    p.add_argument("--modes", default=modes_default, help="comma-separated PersonalAI modes")
    p.add_argument("--base-url", default="http://127.0.0.1:8765", help="personalIA backend URL")
    p.add_argument("--token", default=None, help="bearer token (or PERSONALAI_AUTH_TOKEN)")
    p.add_argument("--repeats", type=int, default=1, help="attempts per cell (pass@k); default 1")
    p.add_argument("--out", default="benchmark-results", help="output directory for reports")


def _select_tasks(args: argparse.Namespace) -> list[Task] | None:
    try:
        tasks = load_tasks(args.tasks)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error loading tasks: {exc}", file=sys.stderr)
        return None
    if args.task_ids:
        wanted = {t.strip() for t in args.task_ids.split(",") if t.strip()}
        tasks = [t for t in tasks if t.id in wanted]
    if not tasks:
        print("no tasks selected", file=sys.stderr)
        return None
    return tasks


def _personal_modes(args: argparse.Namespace) -> list | None:  # type: ignore[type-arg]
    try:
        return [ALL_MODES[m.strip()] for m in args.modes.split(",") if m.strip()]
    except KeyError as exc:
        print(f"unknown mode {exc}; available: {', '.join(ALL_MODES)}", file=sys.stderr)
        return None


def _make_progress(total: int) -> OnProgress:
    """A stderr progress printer: `[i/total] system · mode · task … ok (Nms)`, live as it runs."""
    state = {"i": 0}

    def printer(label: str, result: str | None) -> None:
        if result is None:
            state["i"] += 1
            print(f"[{state['i']:>3}/{total}] {label} … ", end="", flush=True, file=sys.stderr)
        else:
            print(result, file=sys.stderr)

    return printer


def _summary(suite: Suite, out: str) -> int:
    json_path, md_path, html_path = write_report(suite, out)
    total = len(suite.records)
    passed = sum(1 for r in suite.records if r.passed)
    errored = sum(1 for r in suite.records if r.error is not None)
    print(f"ran {total} attempts: {passed} passed, {total - passed} failed ({errored} errored)")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(f"wrote {html_path}  (open in a browser; print to PDF to share)")
    return 0


def _run(args: argparse.Namespace) -> int:
    tasks = _select_tasks(args)
    modes = _personal_modes(args)
    if tasks is None or modes is None:
        return 2
    adapter = PersonalIAAdapter(base_url=args.base_url, token=args.token)
    total = len(tasks) * len(modes) * max(1, args.repeats)
    suite = run_suite(
        tasks=tasks,
        modes=modes,
        sut=adapter,
        repeats=args.repeats,
        on_progress=_make_progress(total),
    )
    return _summary(suite, args.out)


def _compare(args: argparse.Namespace) -> int:
    tasks = _select_tasks(args)
    if tasks is None:
        return 2
    judge = None if args.no_judge else default_judge()
    grader: Grader | None = judge.score if judge is not None else None

    # Assemble the systems first so we can show a global [i/total] progress counter across them.
    p_modes = None if args.no_personalia else _personal_modes(args)
    if not args.no_personalia and p_modes is None:
        return 2
    if args.providers:
        wanted = [p.strip() for p in args.providers.split(",") if p.strip()]
        front = [a for a in (frontier.build(p) for p in wanted) if a is not None]
    else:
        front = frontier.available()
        wanted = [a.provider.name for a in front]
    # Optional tool-equipped ("chat") frontier contestants, using PersonalAI's tools over HTTP.
    front_tools = (
        [
            a
            for a in (
                frontier_tools.build(p, backend_url=args.base_url, backend_token=args.token)
                for p in wanted
            )
            if a is not None
        ]
        if args.frontier_tools
        else []
    )

    reps = max(1, args.repeats)
    total = (
        (len(p_modes) * len(tasks) * reps if p_modes else 0)
        + len(front) * len(tasks) * reps
        + len(front_tools) * len(tasks) * reps
    )
    progress = _make_progress(total)

    records: list[RunRecord] = []
    systems: list[str] = []
    if p_modes is not None:
        pa = PersonalIAAdapter(base_url=args.base_url, token=args.token)
        suite = run_comparison(
            tasks=tasks,
            modes=p_modes,
            systems=[pa],
            grader=grader,
            repeats=args.repeats,
            on_progress=progress,
        )
        records.extend(suite.records)
        systems.append(pa.name)
    if front:
        suite = run_comparison(
            tasks=tasks,
            modes=[RAW],
            systems=front,
            grader=grader,
            repeats=args.repeats,
            on_progress=progress,
        )
        records.extend(suite.records)
        systems.extend(a.name for a in front)
    if front_tools:
        suite = run_comparison(
            tasks=tasks,
            modes=[FRONTIER_TOOLS],
            systems=front_tools,
            grader=grader,
            repeats=args.repeats,
            on_progress=progress,
        )
        records.extend(suite.records)
        systems.extend(a.name for a in front_tools)

    if not records:
        print("no systems to run (PersonalAI skipped and no frontier key present)", file=sys.stderr)
        return 2

    combined = Suite(
        records=records,
        metadata={
            "git_commit": _git_commit(),
            "timestamp": datetime.now(UTC).isoformat(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "systems": systems,
            "modes": sorted({r.mode for r in records}),
            "task_count": len(tasks),
            "repeats": max(1, args.repeats),
            "judge": "off" if judge is None else "claude (gpt fallback)",
        },
    )
    skipped = frontier.missing_keys()
    if skipped:
        print(f"skipped frontier providers (no key): {', '.join(skipped)}")
    if judge is None:
        print("LLM judge OFF — quality (rubric) tasks score 0; set ANTHROPIC_API_KEY to enable")
    return _summary(combined, args.out)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "list-modes":
        for name, mode in ALL_MODES.items():
            print(f"{name:24s} tier={mode.capability_tier}")
        return 0
    if args.command == "compare":
        return _compare(args)
    if args.command == "ui":
        from personalai_benchmarks import ui

        return ui.serve(port=args.port, base_url=args.base_url)
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
