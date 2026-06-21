"""The `remember` tool: writes a durable memory, and fails closed on bad input/embedding (#308)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from personalai_contracts.ports import ToolCall
from personalai_contracts.ports.storage import MemoryItem, MemoryKind
from personalai_tool_builtin import REMEMBER_MANIFEST, RememberTool


class _FakeStore:
    """Captures the single add() the tool performs (the other MemoryStore methods are unused)."""

    def __init__(self) -> None:
        self.added: dict[str, object] | None = None

    async def add(
        self,
        *,
        id: str,
        kind: MemoryKind,
        text: str,
        embedding: Sequence[float],
        confidence: float,
        source: Mapping[str, str],
    ) -> MemoryItem:
        self.added = {
            "id": id,
            "kind": kind,
            "text": text,
            "embedding": list(embedding),
            "confidence": confidence,
            "source": dict(source),
        }
        now = datetime.now(UTC)
        return MemoryItem(
            id=id,
            kind=kind,
            text=text,
            confidence=confidence,
            source=source,
            created_at=now,
            updated_at=now,
        )


async def _ok_embed(text: str) -> Sequence[float]:
    return [0.1, 0.2, 0.3]


def _invoke(store: _FakeStore, args: dict[str, object], embed=_ok_embed):  # type: ignore[no-untyped-def]
    tool = RememberTool(store, embed)  # type: ignore[arg-type]
    return asyncio.run(tool.invoke(ToolCall("remember", "1.0.0", args)))


def test_writes_a_memory_with_full_confidence_and_user_source() -> None:
    store = _FakeStore()
    result = _invoke(store, {"text": "I am married to Viviana Cotirlea"})
    assert result.ok
    assert result.output["text"] == "I am married to Viviana Cotirlea"
    added = store.added
    assert added is not None
    assert result.output["id"] == added["id"]  # the persisted id is returned
    assert added["kind"] is MemoryKind.SEMANTIC  # default kind
    assert added["confidence"] == 1.0  # user stated it directly
    assert added["source"] == {"origin": "user_request"}
    assert added["embedding"] == [0.1, 0.2, 0.3]


def test_honors_an_explicit_kind() -> None:
    store = _FakeStore()
    assert _invoke(store, {"text": "answer concisely", "kind": "preference"}).ok
    assert store.added is not None and store.added["kind"] is MemoryKind.PREFERENCE


def test_unknown_kind_falls_back_to_semantic() -> None:
    store = _FakeStore()
    assert _invoke(store, {"text": "x", "kind": "bogus"}).ok
    assert store.added is not None and store.added["kind"] is MemoryKind.SEMANTIC


def test_empty_text_fails_closed_without_writing() -> None:
    store = _FakeStore()
    result = _invoke(store, {"text": "   "})
    assert not result.ok
    assert "required" in (result.error or "")
    assert store.added is None


def test_embedding_failure_fails_closed_without_writing() -> None:
    store = _FakeStore()

    async def _boom(text: str) -> Sequence[float]:
        raise RuntimeError("embedder down")

    result = _invoke(store, {"text": "remember me"}, embed=_boom)
    assert not result.ok
    assert "could not embed" in (result.error or "")
    assert store.added is None


def test_manifest_is_low_risk_with_no_egress() -> None:
    # A memory write touches only the user's own store: no approval, no network.
    assert REMEMBER_MANIFEST.name == "remember"
    assert REMEMBER_MANIFEST.egress == ()
    assert REMEMBER_MANIFEST.permissions == ()
