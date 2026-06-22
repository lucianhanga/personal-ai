"""Command-line entry point: run a benchmark suite against a local personalIA and write reports.

    python -m personalai_benchmarks run [--tasks DIR] [--modes m1,m2] [--base-url URL]
                                        [--token T] [--out DIR]

Phase 1 has no judge wired in (programmatic scorers only); model-graded tasks report "no judge".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from personalai_benchmarks.adapters import PersonalIAAdapter
from personalai_benchmarks.modes import ALL_MODES
from personalai_benchmarks.report import write_report
from personalai_benchmarks.runner import run_suite
from personalai_benchmarks.tasks import load_tasks

_DEFAULT_TASKS = Path(__file__).resolve().parents[2] / "tasks"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="personalai_benchmarks")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run a benchmark suite and write reports")
    run.add_argument("--tasks", default=str(_DEFAULT_TASKS), help="directory of *.yaml task files")
    run.add_argument(
        "--task-ids", default="", help="comma-separated subset of task ids (default: all)"
    )
    run.add_argument(
        "--modes",
        default=",".join(ALL_MODES),
        help=f"comma-separated modes (default: all). Available: {', '.join(ALL_MODES)}",
    )
    run.add_argument("--base-url", default="http://127.0.0.1:8765", help="personalIA backend URL")
    run.add_argument("--token", default=None, help="bearer token (or PERSONALAI_AUTH_TOKEN)")
    run.add_argument("--out", default="benchmark-results", help="output directory for reports")
    sub.add_parser("list-modes", help="list available benchmark modes")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "list-modes":
        for name, mode in ALL_MODES.items():
            print(f"{name:24s} tier={mode.capability_tier}")
        return 0

    # command == "run"
    try:
        tasks = load_tasks(args.tasks)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error loading tasks: {exc}", file=sys.stderr)
        return 2
    if args.task_ids:
        wanted = {t.strip() for t in args.task_ids.split(",") if t.strip()}
        tasks = [t for t in tasks if t.id in wanted]
    if not tasks:
        print("no tasks selected", file=sys.stderr)
        return 2

    try:
        modes = [ALL_MODES[m.strip()] for m in args.modes.split(",") if m.strip()]
    except KeyError as exc:
        print(f"unknown mode {exc}; available: {', '.join(ALL_MODES)}", file=sys.stderr)
        return 2

    adapter = PersonalIAAdapter(base_url=args.base_url, token=args.token)
    suite = run_suite(tasks=tasks, modes=modes, sut=adapter)
    json_path, md_path = write_report(suite, args.out)

    total = len(suite.records)
    passed = sum(1 for r in suite.records if r.passed)
    errored = sum(1 for r in suite.records if r.error is not None)
    print(f"ran {total} task-runs: {passed} passed, {total - passed} failed ({errored} errored)")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
