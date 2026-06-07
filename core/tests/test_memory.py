"""Short-term memory helpers — pure split + summarizer (fake provider)."""

from __future__ import annotations

import asyncio

import pytest

from personalai_contracts.ports import ChatMessage, Role
from personalai_contracts.testing import FakeModelProvider
from personalai_core import split_recent, summarize


def test_split_recent_splits_older_and_recent() -> None:
    msgs = [ChatMessage(Role.USER, f"m{i}") for i in range(5)]
    older, recent = split_recent(msgs, 2)
    assert [m.content for m in older] == ["m0", "m1", "m2"]
    assert [m.content for m in recent] == ["m3", "m4"]


def test_split_recent_short_history_is_all_recent() -> None:
    msgs = [ChatMessage(Role.USER, "a"), ChatMessage(Role.USER, "b")]
    older, recent = split_recent(msgs, 5)
    assert older == []
    assert len(recent) == 2


def test_split_recent_validates() -> None:
    with pytest.raises(ValueError, match="keep_recent"):
        split_recent([], -1)


def test_summarize_uses_provider() -> None:
    async def _run() -> None:
        s1 = await summarize(FakeModelProvider(), "m", None, [ChatMessage(Role.USER, "hello")])
        assert isinstance(s1, str)
        # prior-summary branch
        s2 = await summarize(
            FakeModelProvider(), "m", "earlier", [ChatMessage(Role.ASSISTANT, "hi")]
        )
        assert isinstance(s2, str)

    asyncio.run(_run())
