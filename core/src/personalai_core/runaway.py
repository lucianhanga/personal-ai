"""Streaming repetition watchdog (#414, Layer 3) — the primary runaway-generation guard.

A real incident: a researcher generation degenerated into a loop, emitting the same reasoning
line (``Let's try: "<candidate>"``) hundreds of times and never converging. None of our existing
bounds caught it: ``agent_max_iterations`` bounds model<->tool steps, ``MAX_ATTEMPTS`` bounds the
graph reflection loop, and ``agent_timeout_seconds`` only fires after minutes of garbage. This is a
single generation looping *internally*, so it must be caught over the streamed deltas themselves.

:class:`RepetitionWatchdog` is fed each text delta as it streams and trips when the output
degenerates into verbatim repetition, on either signal:

- **Repeated line**: the same trimmed, non-trivial line (>= ``min_line_chars``) appears
  >= ``line_repeat_threshold`` times within the recent window (the incident's failure mode).
- **Repeated n-gram**: a word n-gram of length ``ngram_size`` repeats >= ``ngram_repeat_threshold``
  times within the recent window (catches near-identical loops that are not line-delimited).

It is **prompt-independent** (no reliance on the "N words" phrasing) and tuned conservatively to
avoid false positives on legitimate short lists / repeated code idioms — a real run of repeats is
required before it trips. The detector is engine-agnostic: it takes only ``str`` and holds no
provider/LangGraph handles, so the same instance guards both the single-agent loop and the
multi-agent graph (both drive :func:`personalai_core.agent.run_agent`).

Exact line/n-gram matching is sufficient for v1 (the incident is verbatim); FFT-autocorrelation
(SpecRA) is a future upgrade if minor-variation loops appear.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

# Conservative defaults (favor missing a slow loop over killing legitimate output). The line
# detector is the PRIMARY, high-confidence signal (the incident is verbatim whole-line repeats): a
# 12-char line repeated 6 times in the recent window is well past any legitimate short list. The
# n-gram detector is a SECONDARY backstop for non-line-delimited loops, so its threshold is set much
# higher (24) to clear legitimate repeated boilerplate (a 20-item list sharing a phrase, repeated
# code idioms) — only an egregious loop (hundreds of repeats) trips it. Window sizes bound memory
# and keep detection streaming-friendly.
DEFAULT_MIN_LINE_CHARS = 12
DEFAULT_LINE_REPEAT_THRESHOLD = 6
DEFAULT_LINE_WINDOW = 80
DEFAULT_NGRAM_SIZE = 8
DEFAULT_NGRAM_REPEAT_THRESHOLD = 24
DEFAULT_WORD_WINDOW = 400
# The recent word window must additionally be DOMINATED by repetition before the n-gram detector
# trips: at least this fraction of windowed n-grams must be duplicates (few distinct n-grams). A
# tight verbatim loop has only a handful of distinct n-grams however long it runs, so its duplicate
# fraction tends to 1.0; legitimate templated prose (numbered steps, lists with shared boilerplate)
# keeps distinct ~= total, so its duplicate fraction stays near 0 and it does NOT trip. This is what
# separates a degenerate loop from frequent-but-legitimate phrase reuse.
DEFAULT_NGRAM_COVERAGE = 0.5


@dataclass(frozen=True)
class RunawayConfig:
    """Tunable thresholds for the repetition watchdog (#414). Conservative by default so legitimate
    short lists / repeated code idioms do NOT trip; loosen via config without a deploy."""

    enabled: bool = True
    min_line_chars: int = DEFAULT_MIN_LINE_CHARS
    line_repeat_threshold: int = DEFAULT_LINE_REPEAT_THRESHOLD
    line_window: int = DEFAULT_LINE_WINDOW
    ngram_size: int = DEFAULT_NGRAM_SIZE
    ngram_repeat_threshold: int = DEFAULT_NGRAM_REPEAT_THRESHOLD
    ngram_coverage: float = DEFAULT_NGRAM_COVERAGE
    word_window: int = DEFAULT_WORD_WINDOW


class RepetitionWatchdog:
    """A streaming detector over output deltas that trips on verbatim repetition.

    Fed text incrementally via :meth:`feed` (deltas need not align to line/word boundaries — the
    watchdog buffers a partial trailing line and partial trailing token across calls). It keeps
    rolling sliding windows (counts, not full rescans) so cost is O(1) amortized per token. Once
    :attr:`tripped` is true it stays tripped; the caller stops consuming the provider stream.
    """

    def __init__(self, config: RunawayConfig | None = None) -> None:
        self._cfg = config or RunawayConfig()
        self._tripped = False
        self._reason = ""

        # Line detector: a sliding window of recent normalized lines + their live counts.
        self._line_buf = ""  # partial trailing line not yet terminated by a newline
        self._lines: deque[str] = deque()
        self._line_counts: dict[str, int] = {}

        # N-gram detector: a sliding window of recent words + live counts of their n-grams.
        # ``_ngram_total`` is the count of currently-windowed counted n-grams (the coverage base).
        self._word_buf = ""  # partial trailing token not yet terminated by whitespace
        self._words: deque[str] = deque()
        self._ngram_counts: dict[tuple[str, ...], int] = {}
        self._ngram_total = 0

    @property
    def tripped(self) -> bool:
        return self._tripped

    @property
    def reason(self) -> str:
        """A short human-readable reason the watchdog tripped (empty until it does)."""
        return self._reason

    def feed(self, delta: str) -> bool:
        """Feed one streamed text delta. Returns ``True`` once the watchdog has tripped.

        No-ops (returns ``False``) when disabled or already tripped, so the caller can feed
        unconditionally and break on the first ``True``.
        """
        if not self._cfg.enabled or self._tripped or not delta:
            return self._tripped
        self._feed_lines(delta)
        if not self._tripped:
            self._feed_ngrams(delta)
        return self._tripped

    def _trip(self, reason: str) -> None:
        self._tripped = True
        self._reason = reason

    # --- line detector -------------------------------------------------------------------------

    def _feed_lines(self, delta: str) -> None:
        # Accumulate into the partial-line buffer; emit a normalized line on each newline. A delta
        # may carry several newlines or none (mid-line), so split and keep the trailing remainder.
        buf = self._line_buf + delta
        *complete, remainder = buf.split("\n")
        self._line_buf = remainder
        for raw in complete:
            self._push_line(raw)
            if self._tripped:
                return

    def _push_line(self, raw: str) -> None:
        line = raw.strip()
        if len(line) < self._cfg.min_line_chars:
            return  # trivial/short lines never count (legitimate blank lines, short list items)
        self._lines.append(line)
        self._line_counts[line] = self._line_counts.get(line, 0) + 1
        if self._line_counts[line] >= self._cfg.line_repeat_threshold:
            self._trip(
                f"the same line repeated {self._line_counts[line]} times "
                f"(threshold {self._cfg.line_repeat_threshold})"
            )
            return
        while len(self._lines) > self._cfg.line_window:
            old = self._lines.popleft()
            count = self._line_counts.get(old, 0) - 1
            if count <= 0:
                self._line_counts.pop(old, None)
            else:
                self._line_counts[old] = count

    # --- n-gram detector -----------------------------------------------------------------------

    def _feed_ngrams(self, delta: str) -> None:
        # Tokenize on whitespace, keeping a partial trailing token across deltas. ``split()`` on the
        # buffer drops the incomplete tail only when ``delta`` does not end on whitespace.
        buf = self._word_buf + delta
        tokens = buf.split()
        if buf and not buf[-1].isspace() and tokens:
            self._word_buf = tokens.pop()  # last token may be incomplete; hold it back
        else:
            self._word_buf = ""
        for token in tokens:
            self._push_word(token)
            if self._tripped:
                return

    def _counts_as_ngram(self, gram: tuple[str, ...]) -> bool:
        # Only count n-grams with real content. A run of low-entropy short tokens (a "- a" list
        # marker, single-letter bullets) joins to fewer than ``min_line_chars`` and is a legitimate
        # short list, not a degenerate reasoning loop — skip it so it never trips the backstop.
        return len("".join(gram)) >= self._cfg.min_line_chars

    def _push_word(self, word: str) -> None:
        self._words.append(word)
        n = self._cfg.ngram_size
        if len(self._words) >= n:
            gram = tuple(list(self._words)[-n:])
            if self._counts_as_ngram(gram):
                count = self._ngram_counts.get(gram, 0) + 1
                self._ngram_counts[gram] = count
                self._ngram_total += 1
                # Trip only when an n-gram is FREQUENT (>= threshold) AND the window is DOMINATED by
                # repetition: most windowed n-grams are duplicates (few distinct ones). A tight loop
                # of period P has only P distinct n-grams however long it runs, so the duplicate
                # fraction tends to 1.0; legitimate templated prose (a phrase recurring across
                # otherwise-varied sentences, numbered steps) keeps distinct ~= total, so its
                # duplicate fraction stays near 0 and it does NOT trip. This is what separates a
                # degenerate loop from frequent-but-legitimate phrase reuse.
                distinct = len(self._ngram_counts)
                duplicate_fraction = 1.0 - distinct / self._ngram_total
                if (
                    count >= self._cfg.ngram_repeat_threshold
                    and duplicate_fraction >= self._cfg.ngram_coverage
                ):
                    self._trip(
                        f"a {n}-word phrase repeated {count} times "
                        f"(threshold {self._cfg.ngram_repeat_threshold})"
                    )
                    return
        # Evict the oldest word once past the window. The n-gram leaving the window is the one that
        # STARTED at the evicted word (``[evicted] + the next n-1 words``); decrement its count so
        # counts reflect only the recent window (a slow, spread-out repeat must not accumulate
        # forever). Computed BEFORE the pop, while those words are still present. Only n-grams we
        # actually counted are decremented (mirrors the increment's content guard).
        while len(self._words) > self._cfg.word_window:
            if len(self._words) > n:
                stale = tuple(list(self._words)[:n])
                if self._counts_as_ngram(stale) and stale in self._ngram_counts:
                    remaining = self._ngram_counts[stale] - 1
                    if remaining <= 0:
                        self._ngram_counts.pop(stale, None)
                    else:
                        self._ngram_counts[stale] = remaining
                    self._ngram_total -= 1
            self._words.popleft()
