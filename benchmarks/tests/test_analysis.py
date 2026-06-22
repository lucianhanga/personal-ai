"""Length-bias diagnostic: Pearson correlation of answer word-count vs judge score (#334)."""

from __future__ import annotations

from personalai_benchmarks.analysis import length_bias
from personalai_benchmarks.runner import RunRecord


def _rec(
    answer: str, score: float, *, scorer: str = "llm_judge", error: str | None = None
) -> RunRecord:
    return RunRecord(
        task_id="t",
        category="c",
        mode="raw",
        capability_tier="raw",
        answer=answer,
        score=score,
        passed=score >= 0.8,
        explanation="",
        latency_ms=1.0,
        usage={},
        tool_calls=[],
        config_used={},
        error=error,
        scorer=scorer,
    )


def _words(n: int) -> str:
    return " ".join(["w"] * n)


def test_perfect_positive_correlation_is_flagged() -> None:
    # longer answer -> higher score, monotonically: r should be ~ +1 and flagged.
    recs = [_rec(_words(n), n / 10.0) for n in (1, 2, 3, 4, 5, 6)]
    bias = length_bias(recs)
    assert bias is not None
    assert bias.n == 6
    assert bias.pearson_r > 0.99 and bias.flagged
    assert "FLAG" in bias.summary()


def test_no_correlation_is_not_flagged() -> None:
    # score independent of length.
    recs = [
        _rec(_words(1), 0.9),
        _rec(_words(50), 0.9),
        _rec(_words(2), 0.2),
        _rec(_words(40), 0.2),
        _rec(_words(3), 0.6),
        _rec(_words(30), 0.6),
    ]
    bias = length_bias(recs)
    assert bias is not None and not bias.flagged
    assert "ok" in bias.summary()


def test_below_min_samples_returns_none() -> None:
    assert length_bias([_rec(_words(3), 0.5), _rec(_words(9), 0.9)]) is None


def test_only_judge_graded_records_count() -> None:
    # programmatic rows are ignored; too few judge rows -> None.
    recs = [_rec(_words(i), 0.5, scorer="includes") for i in range(10)]
    recs += [_rec(_words(2), 0.5), _rec(_words(8), 0.9)]
    assert length_bias(recs) is None


def test_errored_and_empty_answers_are_skipped() -> None:
    recs = [_rec(_words(n), n / 10.0) for n in (1, 2, 3, 4, 5)]
    recs.append(_rec("", 0.9, error="boom"))  # skipped: errored + empty
    bias = length_bias(recs)
    assert bias is not None and bias.n == 5


def test_flat_scores_have_no_defined_correlation() -> None:
    # every score identical -> zero variance on one axis -> None (not a spurious 0.0 flag).
    recs = [_rec(_words(n), 0.5) for n in (1, 2, 3, 4, 5, 6)]
    assert length_bias(recs) is None
