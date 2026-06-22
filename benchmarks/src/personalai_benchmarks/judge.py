"""LLM-as-judge quality scoring (M-Bench Phase 2, #322).

Grades open-ended answers a string match can't: a strong judge model rates the answer against a
rubric (1–5 per criterion, chain-of-thought then score, reference-guided when a gold answer exists),
returning structured JSON. Research-driven guards: judge at temperature 0 with a pinned prompt +
model (a judge change bumps ``JUDGE_PROMPT_VERSION``); instruct it to ignore length/formatting
(verbosity bias); and — critically, since Claude is both a contestant and the judge — **a model
never judges its own family** (self-preference bias): a contestant from the judge's vendor is graded
by the fallback judge instead. The judge call is injected, so this module needs no network or keys
to test.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from personalai_benchmarks import frontier
from personalai_benchmarks.scoring import Score, score_task
from personalai_benchmarks.tasks import Task

# Bump when the prompt or output schema changes — it is part of the benchmark version.
JUDGE_PROMPT_VERSION = "v1"
# score >= this (out of 5) counts as a pass for the boolean leaderboard.
DEFAULT_PASS_THRESHOLD = 4

# A judge call: take chat messages, return the model's raw text reply (empty string on failure).
JudgeCall = Callable[[Sequence[Mapping[str, str]]], str]


class Verdict(BaseModel):
    """The judge's structured grade. ``criteria`` are 1–5; ``score`` is the overall 1–5."""

    model_config = ConfigDict(extra="ignore")

    reasoning: str = ""
    criteria: dict[str, int] = Field(default_factory=dict)
    score: int


_SYSTEM = (
    "You are an impartial expert evaluator. Judge ONLY the quality of the answer to the question: "
    "its correctness, completeness, grounding (claims supported, not fabricated), and helpfulness. "
    "IGNORE length, formatting, and tone — a concise correct answer must not score lower than a "
    "verbose one. Do not assume which system produced the answer. Think step by step, then "
    "grade each criterion from 1 (poor) to 5 (excellent) and give an overall 1-5 score. Return "
    'ONLY JSON: {"reasoning": str, "criteria": {"correctness": int, "completeness": int, '
    '"grounding": int, "helpfulness": int}, "score": int}.'
)


def _user_prompt(question: str, answer: str, reference: str | None, rubric: str | None) -> str:
    parts = [f"[QUESTION]\n{question}\n"]
    if reference:
        parts.append(f"[REFERENCE ANSWER] (a known-good answer to grade against)\n{reference}\n")
    if rubric:
        parts.append(f"[TASK-SPECIFIC CRITERIA]\n{rubric}\n")
    parts.append(f"[ANSWER TO GRADE]\n{answer}\n")
    return "\n".join(parts)


def grade(
    *,
    question: str,
    answer: str,
    reference: str | None,
    rubric: str | None,
    call: JudgeCall,
) -> Verdict | None:
    """Ask the judge to grade ``answer``; return a :class:`Verdict`, or None if the judge failed."""
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _user_prompt(question, answer, reference, rubric)},
    ]
    raw = call(messages)
    if not raw:
        return None
    try:
        payload = json.loads(_extract_json(raw))
        return Verdict.model_validate(payload)
    except (ValueError, TypeError):
        return None


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


def _vendor(system_name: str) -> str:
    # Frontier adapters name themselves "<vendor>:<model>"; everything else (e.g. "personalia") has
    # no vendor prefix and never collides with the judge's vendor.
    return system_name.split(":", 1)[0] if ":" in system_name else system_name


class LlmJudge:
    """A Task-level grader. Uses the LLM judge for rubric tasks, programmatic scoring otherwise.

    ``vendor`` is the judge's own vendor; a contestant whose vendor matches is graded by
    ``fallback`` (different vendor) to avoid self-preference bias.
    """

    def __init__(
        self,
        call: JudgeCall,
        *,
        vendor: str,
        fallback: JudgeCall | None = None,
        fallback_vendor: str | None = None,
        pass_threshold: int = DEFAULT_PASS_THRESHOLD,
    ) -> None:
        self._call = call
        self._vendor = vendor
        self._fallback = fallback
        self._fallback_vendor = fallback_vendor
        self._threshold = pass_threshold

    def _call_for(self, system_name: str) -> tuple[JudgeCall, str]:
        # Self-preference guard: don't let the judge grade its own family.
        if _vendor(system_name) == self._vendor and self._fallback is not None:
            return self._fallback, self._fallback_vendor or "fallback"
        return self._call, self._vendor

    def score(self, task: Task, answer: str, system_name: str) -> Score:
        # Tasks with a plain `expected` (verifiable) stay programmatic; rubric tasks use the judge.
        is_rubric = task.rubric is not None and task.rubric.get("type") == "model_graded"
        if not is_rubric:
            return score_task(task, answer)
        question = next(
            (m.content for m in reversed(task.input) if m.role == "user"),
            task.input[-1].content if task.input else "",
        )
        call, judge_vendor = self._call_for(system_name)
        verdict = grade(
            question=question,
            answer=answer,
            reference=task.expected,
            rubric=str(task.rubric.get("criteria", "")) if task.rubric else None,
            call=call,
        )
        if verdict is None:
            return Score(0.0, False, "judge unavailable or returned invalid output", "llm_judge")
        passed = verdict.score >= self._threshold
        return Score(
            value=verdict.score / 5.0,
            passed=passed,
            explanation=f"[judge:{judge_vendor}] {verdict.score}/5 — {verdict.reasoning}"[:500],
            scorer="llm_judge",
            params={"judge_vendor": judge_vendor, "prompt_version": JUDGE_PROMPT_VERSION},
        )


def make_call(provider_name: str, model: str | None = None) -> JudgeCall | None:
    """A judge call backed by a frontier provider (temperature 0), or None if its key is absent."""
    adapter = frontier.build(provider_name, model=model)
    if adapter is None:
        return None

    def call(messages: Sequence[Mapping[str, str]]) -> str:
        return adapter.run(messages, {"temperature": 0}).answer

    return call


def default_judge(
    *,
    primary: str = "anthropic",
    primary_model: str | None = None,
    fallback: str = "openai",
    fallback_model: str | None = None,
) -> LlmJudge | None:
    """The configured judge (primary + self-preference fallback), or None if the primary key is
    missing (quality grading is then skipped). Defaults: Claude judge, GPT fallback for Claude."""
    primary_call = make_call(primary, primary_model)
    if primary_call is None:
        return None
    fallback_call = make_call(fallback, fallback_model)
    return LlmJudge(primary_call, vendor=primary, fallback=fallback_call, fallback_vendor=fallback)
