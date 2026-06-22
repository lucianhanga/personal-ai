"""LLM-judge scoring: rubric grading, self-preference fallback, programmatic passthrough (#322)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from personalai_benchmarks.judge import JUDGE_PROMPT_VERSION, LlmJudge, grade
from personalai_benchmarks.tasks import Task


def _verdict(score: int) -> str:
    # v2 form-filling shape: each criterion carries a justification written before its score.
    def dim(s: int) -> dict[str, object]:
        return {"justification": "because reasons", "score": s}

    return json.dumps(
        {
            "reasoning": "the answer is accurate and complete",
            "criteria": {
                "correctness": dim(score),
                "completeness": dim(score),
                "grounding": dim(5),
                "helpfulness": dim(4),
            },
            "score": score,
        }
    )


def _verdict_v1(score: int) -> str:
    # Legacy bare-int criteria; the judge must still parse it.
    return json.dumps(
        {
            "reasoning": "ok",
            "criteria": {"correctness": score, "completeness": score},
            "score": score,
        }
    )


def _recording_call(reply: str, log: list[Sequence[Mapping[str, str]]] | None = None):  # type: ignore[no-untyped-def]
    def call(messages: Sequence[Mapping[str, str]]) -> str:
        if log is not None:
            log.append(messages)
        return reply

    return call


def _rubric_task() -> Task:
    return Task.model_validate(
        {
            "id": "q1",
            "category": "qa",
            "capability_tier": "raw",
            "input": [{"role": "user", "content": "Summarize the water cycle."}],
            "expected": "Evaporation, condensation, precipitation, collection.",
            "rubric": {"type": "model_graded", "criteria": "mentions the main stages"},
        }
    )


def test_grade_parses_a_verdict() -> None:
    v = grade(
        question="Q", answer="A", reference="R", rubric="crit", call=_recording_call(_verdict(5))
    )
    assert v is not None and v.score == 5
    assert v.criteria["correctness"].score == 5
    assert v.criteria["correctness"].justification == "because reasons"
    assert v.criterion_scores == {
        "correctness": 5,
        "completeness": 5,
        "grounding": 5,
        "helpfulness": 4,
    }


def test_grade_tolerates_legacy_bare_int_criteria() -> None:
    v = grade(
        question="Q", answer="A", reference=None, rubric=None, call=_recording_call(_verdict_v1(3))
    )
    assert v is not None and v.score == 3
    assert v.criterion_scores == {"correctness": 3, "completeness": 3}


def test_explanation_lists_per_dimension_scores() -> None:
    judge = LlmJudge(_recording_call(_verdict(5)), vendor="anthropic")
    score = judge.score(_rubric_task(), "ans", "groq:llama")
    assert "correctness=5" in score.explanation and "helpfulness=4" in score.explanation


def test_grade_returns_none_on_garbage() -> None:
    assert (
        grade(question="Q", answer="A", reference=None, rubric=None, call=_recording_call("nope"))
        is None
    )


def test_rubric_task_is_scored_by_the_judge() -> None:
    judge = LlmJudge(_recording_call(_verdict(5)), vendor="anthropic")
    score = judge.score(
        _rubric_task(), "Water evaporates, condenses, falls, collects.", "groq:llama"
    )
    assert score.scorer == "llm_judge"
    assert score.passed and score.value == 1.0
    assert score.params["prompt_version"] == JUDGE_PROMPT_VERSION
    assert score.params["judge_vendor"] == "anthropic"


def test_low_score_fails_the_threshold() -> None:
    judge = LlmJudge(_recording_call(_verdict(2)), vendor="anthropic")
    score = judge.score(_rubric_task(), "wrong", "openai:gpt-4o")
    assert not score.passed and score.value == 0.4


def test_self_preference_routes_claude_rows_to_the_fallback() -> None:
    primary_log: list[Sequence[Mapping[str, str]]] = []
    fallback_log: list[Sequence[Mapping[str, str]]] = []
    judge = LlmJudge(
        _recording_call(_verdict(5), primary_log),
        vendor="anthropic",
        fallback=_recording_call(_verdict(5), fallback_log),
        fallback_vendor="openai",
    )
    # An Anthropic contestant must NOT be judged by the Anthropic judge.
    score = judge.score(_rubric_task(), "ans", "anthropic:claude-3-5-sonnet")
    assert score.params["judge_vendor"] == "openai"
    assert len(fallback_log) == 1 and len(primary_log) == 0
    # A non-Anthropic contestant uses the primary judge.
    judge.score(_rubric_task(), "ans", "deepseek:deepseek-chat")
    assert len(primary_log) == 1


def test_judge_failure_fails_closed() -> None:
    judge = LlmJudge(_recording_call(""), vendor="anthropic")  # empty reply -> grade None
    score = judge.score(_rubric_task(), "ans", "groq:llama")
    assert not score.passed and "unavailable" in score.explanation


def test_non_rubric_task_stays_programmatic() -> None:
    # A task with `expected` and no rubric is graded by string match — the judge is never called.
    task = Task.model_validate(
        {
            "id": "m1",
            "category": "reasoning",
            "capability_tier": "raw",
            "input": [{"role": "user", "content": "2+2?"}],
            "expected": "4",
            "metadata": {"match": "includes"},
        }
    )

    def _boom(messages: Sequence[Mapping[str, str]]) -> str:
        raise AssertionError("judge must not be called for a programmatic task")

    judge = LlmJudge(_boom, vendor="anthropic")
    assert judge.score(task, "the answer is 4", "openai:gpt-4o").passed
