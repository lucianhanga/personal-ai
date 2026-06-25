"""Streaming repetition watchdog (#414, Layer 3) unit tests.

Proves the detector trips on a real run of verbatim repetition (the incident: the same reasoning
line hundreds of times) but does NOT trip on legitimate varied output or a bounded short list —
the false-positive boundary that protects normal short lists / repeated code idioms.
"""

from __future__ import annotations

from personalai_core.runaway import RepetitionWatchdog, RunawayConfig


def _feed_all(wd: RepetitionWatchdog, deltas: list[str]) -> bool:
    tripped = False
    for d in deltas:
        if wd.feed(d):
            tripped = True
            break
    return tripped


def test_repeated_line_trips_after_threshold() -> None:
    # The incident: the same non-trivial line repeated many times.
    wd = RepetitionWatchdog()
    line = 'Let\'s try: "a candidate summary"\n'
    tripped = _feed_all(wd, [line] * 50)
    assert tripped is True
    assert wd.tripped is True
    assert "repeated" in wd.reason


def test_repeated_line_does_not_trip_below_threshold() -> None:
    # Five repeats with the default threshold of six must NOT trip (boundary, just under).
    wd = RepetitionWatchdog(RunawayConfig(line_repeat_threshold=6))
    line = "this is a sufficiently long repeated line\n"
    tripped = _feed_all(wd, [line] * 5)
    assert tripped is False
    assert wd.tripped is False


def test_short_lines_never_count() -> None:
    # Short lines (below min_line_chars) are legitimate (blank lines, short list markers) and must
    # never trip, no matter how many times they repeat.
    wd = RepetitionWatchdog(RunawayConfig(min_line_chars=12))
    tripped = _feed_all(wd, ["- a\n"] * 100)
    assert tripped is False


def test_varied_output_does_not_trip() -> None:
    # A normal, varied stream of distinct lines must not trip the line OR n-gram detector.
    wd = RepetitionWatchdog()
    deltas = [
        f"This is distinct sentence number {i} about a different topic entirely.\n"
        for i in range(200)
    ]
    assert _feed_all(wd, deltas) is False


def test_legitimate_bounded_list_does_not_trip() -> None:
    # A markdown list of 20 similar-but-distinct bullets is legitimate and must NOT trip (the
    # explicit false-positive boundary from the issue's acceptance criteria).
    wd = RepetitionWatchdog()
    bullets = [
        f"- Item number {i}: a short description of this distinct entry.\n" for i in range(20)
    ]
    assert _feed_all(wd, bullets) is False


def test_repeated_ngram_trips() -> None:
    # A near-identical loop that is not line-delimited: the same long phrase repeated many times in
    # one continuous stream trips the n-gram detector. The line detector is disabled via a high line
    # threshold (NOT via min_line_chars, which also gates n-gram content).
    wd = RepetitionWatchdog(RunawayConfig(line_repeat_threshold=100_000, ngram_repeat_threshold=24))
    phrase = "the quick brown fox jumps over the lazy dog and "
    tripped = _feed_all(wd, [phrase] * 60)
    assert tripped is True
    assert "phrase repeated" in wd.reason


def test_ngram_detector_does_not_trip_on_varied_prose() -> None:
    wd = RepetitionWatchdog(RunawayConfig(line_repeat_threshold=100_000))
    words = " ".join(f"word{i}" for i in range(2000)) + " "
    assert wd.feed(words) is False


def test_ngram_detector_does_not_trip_on_templated_prose() -> None:
    # Templated output (a shared phrase across otherwise-varied sentences, like numbered steps)
    # reuses a phrase often but it never DOMINATES the window, so the coverage gate keeps it safe.
    wd = RepetitionWatchdog(RunawayConfig(line_repeat_threshold=100_000))
    deltas = [
        f"Step number {i} explains a different idea about a separate distinct subtopic here. "
        for i in range(300)
    ]
    assert _feed_all(wd, deltas) is False


def test_disabled_watchdog_never_trips() -> None:
    wd = RepetitionWatchdog(RunawayConfig(enabled=False))
    line = "this is a sufficiently long repeated line\n"
    assert _feed_all(wd, [line] * 100) is False
    assert wd.tripped is False


def test_deltas_split_across_line_boundaries() -> None:
    # Deltas need not align to newline boundaries: feeding the same line in fragments must still
    # accumulate and trip (proves the partial-line buffering).
    wd = RepetitionWatchdog(RunawayConfig(line_repeat_threshold=6, min_line_chars=12))
    fragments: list[str] = []
    for _ in range(10):
        fragments += ["this is a long ", "repeated line value", "\n"]
    assert _feed_all(wd, fragments) is True


def test_tripped_is_sticky() -> None:
    wd = RepetitionWatchdog(RunawayConfig(line_repeat_threshold=6))
    line = "this is a sufficiently long repeated line\n"
    _feed_all(wd, [line] * 50)
    assert wd.tripped is True
    # Further feeds keep returning tripped without error.
    assert wd.feed("anything else entirely\n") is True
