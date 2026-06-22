"""Judge-quality diagnostics (#334).

A reliable LLM judge should grade on *content*, not *length*. If its scores correlate with how many
words the answer has, that is a tell-tale of verbosity bias. :func:`length_bias` measures the
Pearson correlation between answer word-count and judge score over judge-graded runs so a sweep can
be sanity-checked; the ``compare`` summary surfaces it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from personalai_benchmarks.runner import RunRecord

# |r| at or above this over enough samples is worth flagging (a moderate correlation).
FLAG_THRESHOLD = 0.3
# Below this many judged answers, a correlation is noise — don't report one.
MIN_SAMPLES = 5


@dataclass(frozen=True)
class LengthBias:
    """Pearson r of answer length (words) vs judge score; flagged when the magnitude is high."""

    n: int
    pearson_r: float
    flagged: bool

    def summary(self) -> str:
        verdict = "FLAG: scores track answer length" if self.flagged else "ok"
        return (
            f"length-bias check: r={self.pearson_r:+.2f} over n={self.n} judged answers ({verdict})"
        )


def length_bias(
    records: Sequence[RunRecord],
    *,
    scorer: str = "llm_judge",
    threshold: float = FLAG_THRESHOLD,
    min_samples: int = MIN_SAMPLES,
) -> LengthBias | None:
    """Correlate answer word-count with score over ``scorer``-graded, error-free records.

    Returns None when there are fewer than ``min_samples`` usable points (a correlation would be
    noise) or when either axis has no variance (correlation undefined).
    """
    points = [
        (len(r.answer.split()), r.score)
        for r in records
        if r.scorer == scorer and r.error is None and r.answer
    ]
    if len(points) < min_samples:
        return None
    lengths = [float(x) for x, _ in points]
    scores = [float(y) for _, y in points]
    r = _pearson(lengths, scores)
    if r is None:
        return None
    return LengthBias(n=len(points), pearson_r=r, flagged=abs(r) >= threshold)


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    cov = sum(a * b for a, b in zip(dx, dy, strict=True))
    var_x = sum(a * a for a in dx)
    var_y = sum(b * b for b in dy)
    if var_x == 0 or var_y == 0:  # a flat axis: correlation is undefined
        return None
    return float(cov / (var_x**0.5 * var_y**0.5))
