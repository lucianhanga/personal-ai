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

from personalai_benchmarks import frontier
from personalai_benchmarks.adapters import PersonalIAAdapter
from personalai_benchmarks.analysis import length_bias
from personalai_benchmarks.cache import ResultCache
from personalai_benchmarks.judge import JUDGE_PROMPT_VERSION, strongest_judge
from personalai_benchmarks.modes import ALL_MODES, RAW
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
        "--models",
        default="",
        help="comma frontier contestants: a provider (= all its models) or 'provider:model' "
        f"(default: one per provider with a key). Providers: {', '.join(frontier.PROVIDERS)}",
    )
    cmp.add_argument(
        "--categories",
        default="",
        help="comma-separated task categories to run (groups of tasks); combine with --task-ids",
    )
    cmp.add_argument(
        "--no-personalia", action="store_true", help="skip the local PersonalAI system"
    )
    cmp.add_argument(
        "--cache-file",
        default="benchmark-results/cache.json",
        help="frontier result cache (deterministic frontier cells are reused across runs)",
    )
    cmp.add_argument(
        "--no-cache",
        action="store_true",
        help="don't reuse or store cached frontier results (re-run everything)",
    )
    cmp.add_argument(
        "--refresh",
        action="store_true",
        help="re-run frontier models even if cached, and refresh the cache (models changed)",
    )

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
    ids = {t.strip() for t in args.task_ids.split(",") if t.strip()}
    cats = {c.strip() for c in getattr(args, "categories", "").split(",") if c.strip()}
    if ids or cats:  # union: run the named categories and/or the named task ids
        tasks = [t for t in tasks if t.id in ids or t.category in cats]
    if not tasks:
        print("no tasks selected", file=sys.stderr)
        return None
    return tasks


def _frontier_models(spec: str) -> list[frontier.OpenAICompatAdapter]:
    """Build frontier contestants from a --models spec: each token is a provider (= all its models)
    or 'provider:model'. Empty spec = one representative per provider that has a key."""
    if not spec.strip():
        return frontier.available()
    out: list[frontier.OpenAICompatAdapter] = []
    for token in (t.strip() for t in spec.split(",") if t.strip()):
        if ":" in token:
            provider, model = token.split(":", 1)
            adapter = frontier.build(provider, model=model)
            if adapter is not None:
                out.append(adapter)
        else:
            out.extend(frontier.build_tier(token, "all"))
    return out


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
    if suite.metadata.get("interrupted"):
        print("PARTIAL report (run was stopped before completion)")
    print(f"ran {total} attempts: {passed} passed, {total - passed} failed ({errored} errored)")
    bias = length_bias(suite.records)
    if bias is not None:
        print(bias.summary())
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(f"wrote {html_path}  (open in a browser; print to PDF to share)")
    return 0


def _timestamped_out(base: str) -> str:
    """A per-run report directory under ``base`` (history, never overwrites a previous run)."""
    return str(Path(base) / datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S"))


def _partial_metadata(
    records: list[RunRecord], args: argparse.Namespace, judge_label: str
) -> dict[str, object]:
    """Metadata for a partial (Ctrl-C-stopped) single-system run, derived from collected records."""
    return {
        "git_commit": _git_commit(),
        "timestamp": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "sut": records[0].system,
        "modes": sorted({r.mode for r in records}),
        "task_count": len({r.task_id for r in records}),
        "repeats": max(1, args.repeats),
        "judge": judge_label,
        "interrupted": True,
    }


def _run(args: argparse.Namespace) -> int:
    tasks = _select_tasks(args)
    modes = _personal_modes(args)
    if tasks is None or modes is None:
        return 2
    adapter = PersonalIAAdapter(base_url=args.base_url, token=args.token)
    total = len(tasks) * len(modes) * max(1, args.repeats)
    collected: list[RunRecord] = []
    suite: Suite | None = None
    try:
        suite = run_suite(
            tasks=tasks,
            modes=modes,
            sut=adapter,
            repeats=args.repeats,
            on_progress=_make_progress(total),
            sink=collected,
        )
    except KeyboardInterrupt:
        print("\nstopped — writing a partial report from results so far", file=sys.stderr)
    if suite is None:  # interrupted: build a partial suite from what we collected
        if not collected:
            print("stopped before any result was collected", file=sys.stderr)
            return 130
        suite = Suite(records=collected, metadata=_partial_metadata(collected, args, "off"))
    return _summary(suite, _timestamped_out(args.out))


def _compare(args: argparse.Namespace) -> int:
    tasks = _select_tasks(args)
    if tasks is None:
        return 2
    # The judge is always on: the strongest available frontier model (fixed ranking), shown below.
    judge, judge_label = strongest_judge()
    grader: Grader | None = judge.score if judge is not None else None

    # Assemble the systems first so we can show a global [i/total] progress counter across them.
    p_modes = None if args.no_personalia else _personal_modes(args)
    if not args.no_personalia and p_modes is None:
        return 2
    front = _frontier_models(args.models)

    reps = max(1, args.repeats)
    total = (len(p_modes) * len(tasks) * reps if p_modes else 0) + len(front) * len(tasks) * reps
    progress = _make_progress(total)

    collected: list[RunRecord] = []
    pa = PersonalIAAdapter(base_url=args.base_url, token=args.token) if p_modes else None
    systems = ([pa.name] if pa else []) + [a.name for a in front]

    # Frontier results are deterministic (temperature 0), so the frontier tier is cached and reused
    # across runs — only the local model is always re-run. The tag invalidates judged cells when the
    # judge model or prompt changes.
    cache = ResultCache.load(args.cache_file, enabled=not args.no_cache, refresh=args.refresh)
    cache_tag = "nojudge" if judge is None else f"judge:{JUDGE_PROMPT_VERSION}:{judge_label}"

    # Run all contestants into one live `collected` sink, so Ctrl-C (stop) still yields a partial
    # report from whatever finished. Each block contributes its records before the next begins.
    interrupted = False
    try:
        if pa is not None and p_modes is not None:
            run_comparison(
                tasks=tasks,
                modes=p_modes,
                systems=[pa],
                grader=grader,
                repeats=args.repeats,
                on_progress=progress,
                sink=collected,
            )
        if front:
            run_comparison(
                tasks=tasks,
                modes=[RAW],
                systems=front,
                grader=grader,
                repeats=args.repeats,
                on_progress=progress,
                sink=collected,
                cache=cache,
                cache_tag=cache_tag,
            )
    except KeyboardInterrupt:
        interrupted = True
        print("\nstopped — writing a partial report from results so far", file=sys.stderr)
    finally:
        cache.save()  # persist completed frontier cells even if the run was stopped

    if not collected:
        if interrupted:
            print("stopped before any result was collected", file=sys.stderr)
            return 130
        print("no systems to run (PersonalAI skipped and no frontier key present)", file=sys.stderr)
        return 2

    combined = Suite(
        records=collected,
        metadata={
            "git_commit": _git_commit(),
            "timestamp": datetime.now(UTC).isoformat(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "systems": systems,
            "modes": sorted({r.mode for r in collected}),
            "task_count": len(tasks),
            "repeats": max(1, args.repeats),
            "judge": judge_label,
            "interrupted": interrupted,
        },
    )
    print(f"judge: {judge_label}")
    skipped = frontier.missing_keys()
    if skipped:
        print(f"skipped frontier providers (no key): {', '.join(skipped)}")
    if judge is None:
        print("LLM judge unavailable — rubric tasks score 0; set a frontier API key to enable")
    if cache.enabled:
        print(
            f"frontier cache: reused {cache.hits}, stored {cache.stored} "
            f"new ({args.cache_file}) — local model always re-runs"
        )
    return _summary(combined, _timestamped_out(args.out))


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
