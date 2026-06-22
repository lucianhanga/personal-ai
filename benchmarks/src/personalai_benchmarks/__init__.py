"""PersonalAI benchmark harness (M-Bench, #313).

Drives personalIA through the non-streaming ``/api/v1/assistant/execute`` endpoint across benchmark
modes (single/no-tools, single+tools+mcp, multi+tools+mcp, ...) and scores the results into a
capability-tier-labelled leaderboard. Dev-only; talks to the backend over HTTP, so it does not
import any app package."""

from personalai_benchmarks import frontier
from personalai_benchmarks.adapters import PersonalIAAdapter, RunResult, SystemUnderTest
from personalai_benchmarks.judge import LlmJudge, default_judge
from personalai_benchmarks.modes import ALL_MODES, Mode
from personalai_benchmarks.runner import RunRecord, Suite, run_comparison, run_suite
from personalai_benchmarks.scoring import Score, score_task
from personalai_benchmarks.tasks import Task, load_tasks

__all__ = [
    "ALL_MODES",
    "LlmJudge",
    "Mode",
    "PersonalIAAdapter",
    "RunRecord",
    "RunResult",
    "Score",
    "Suite",
    "SystemUnderTest",
    "Task",
    "default_judge",
    "frontier",
    "load_tasks",
    "run_comparison",
    "run_suite",
    "score_task",
]
