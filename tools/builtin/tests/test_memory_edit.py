"""update_memory / forget_memory: resolve by similarity, then supersede (reversible) (#314)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from personalai_contracts.ports import MemoryKind, ToolCall
from personalai_contracts.testing import InMemoryMemoryStore
from personalai_tool_builtin import (
    FORGET_MEMORY_MANIFEST,
    UPDATE_MEMORY_MANIFEST,
    ForgetMemoryTool,
    UpdateMemoryTool,
)


async def _const_embed(text: str) -> Sequence[float]:
    # Every text maps to the same unit vector, so the single stored memory is always the top match
    # (score 1.0). Embedding never fails here.
    return [1.0, 0.0, 0.0]


async def _seed(store: InMemoryMemoryStore, text: str) -> str:
    item = await store.add(
        id="m1",
        kind=MemoryKind.SEMANTIC,
        text=text,
        embedding=[1.0, 0.0, 0.0],
        confidence=1.0,
        source={"origin": "user_request"},
    )
    return item.id


def test_update_supersedes_old_and_stores_correction() -> None:
    async def run() -> None:
        store = InMemoryMemoryStore()
        await _seed(store, "User is friends with Doru Lorinz.")
        tool = UpdateMemoryTool(store, _const_embed)
        result = await tool.invoke(
            ToolCall(
                "update_memory",
                "1.0.0",
                {"query": "friends list", "new_text": "User is friends with Doru Lorint."},
            )
        )
        assert result.ok
        assert result.output["to"] == "User is friends with Doru Lorint."
        assert result.output["updated_from"] == "User is friends with Doru Lorinz."
        visible = await store.list()  # old is superseded (hidden); only the correction remains
        assert len(visible) == 1
        assert visible[0].text == "User is friends with Doru Lorint."

    asyncio.run(run())


def test_forget_hides_the_matching_memory() -> None:
    async def run() -> None:
        store = InMemoryMemoryStore()
        await _seed(store, "User lives in Munich.")
        result = await ForgetMemoryTool(store, _const_embed).invoke(
            ToolCall("forget_memory", "1.0.0", {"query": "where the user lives"})
        )
        assert result.ok and result.output["forgotten"] == "User lives in Munich."
        assert await store.list() == []  # superseded -> hidden from list

    asyncio.run(run())


def test_no_match_fails_closed() -> None:
    async def run() -> None:
        store = InMemoryMemoryStore()  # empty -> nothing to resolve
        upd = await UpdateMemoryTool(store, _const_embed).invoke(
            ToolCall("update_memory", "1.0.0", {"query": "x", "new_text": "y"})
        )
        assert not upd.ok and "no memory matching" in (upd.error or "")
        forget = await ForgetMemoryTool(store, _const_embed).invoke(
            ToolCall("forget_memory", "1.0.0", {"query": "x"})
        )
        assert not forget.ok and "no memory matching" in (forget.error or "")

    asyncio.run(run())


def test_update_requires_both_args() -> None:
    async def run() -> None:
        store = InMemoryMemoryStore()
        await _seed(store, "fact")
        result = await UpdateMemoryTool(store, _const_embed).invoke(
            ToolCall("update_memory", "1.0.0", {"query": "fact"})  # missing new_text
        )
        assert not result.ok and "required" in (result.error or "")

    asyncio.run(run())


def test_low_similarity_is_not_acted_on() -> None:
    async def run() -> None:
        store = InMemoryMemoryStore()
        # Seed with an orthogonal vector so the const-embed query scores 0 (< RESOLVE_THRESHOLD).
        await store.add(
            id="m1",
            kind=MemoryKind.SEMANTIC,
            text="unrelated",
            embedding=[0.0, 1.0, 0.0],
            confidence=1.0,
            source={},
        )
        result = await ForgetMemoryTool(store, _const_embed).invoke(
            ToolCall("forget_memory", "1.0.0", {"query": "something else entirely"})
        )
        assert not result.ok  # below the confidence floor -> refuse to act on the wrong memory
        assert len(await store.list()) == 1  # left untouched

    asyncio.run(run())


def test_manifests_are_low_risk_no_egress() -> None:
    for manifest in (UPDATE_MEMORY_MANIFEST, FORGET_MEMORY_MANIFEST):
        assert manifest.egress == () and manifest.permissions == ()
