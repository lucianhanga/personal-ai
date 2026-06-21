"""The `remember` tool: reports the consolidation outcome; fails closed on bad input (#308/#310)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from personalai_contracts.ports import MemoryItem, MemoryKind, ToolCall, ToolResult
from personalai_tool_builtin import REMEMBER_MANIFEST, RememberTool, SaveMemory


def _item(text: str) -> MemoryItem:
    now = datetime.now(UTC)
    return MemoryItem(
        id="mem-1",
        kind=MemoryKind.SEMANTIC,
        text=text,
        confidence=1.0,
        source={"origin": "user_request"},
        created_at=now,
        updated_at=now,
    )


def _invoke(save: SaveMemory, args: dict[str, object]) -> ToolResult:
    return asyncio.run(RememberTool(save).invoke(ToolCall("remember", "1.0.0", args)))


def test_reports_a_new_memory_with_its_id() -> None:
    calls: list[tuple[str, str]] = []

    async def save(text: str, kind: str) -> tuple[str, MemoryItem | None]:
        calls.append((text, kind))
        return "add", _item(text)

    result = _invoke(save, {"text": "I am married to Viviana"})
    assert result.ok
    assert result.output == {"op": "add", "id": "mem-1", "text": "I am married to Viviana"}
    assert calls == [("I am married to Viviana", "semantic")]  # default kind, trimmed text


def test_reports_an_update_when_a_fact_was_reconciled() -> None:
    async def save(text: str, kind: str) -> tuple[str, MemoryItem | None]:
        return "update", _item(text)

    result = _invoke(save, {"text": "I am married to Viviana", "kind": "semantic"})
    assert result.ok and result.output["op"] == "update"


def test_noop_is_reported_as_already_remembered() -> None:
    async def save(text: str, kind: str) -> tuple[str, MemoryItem | None]:
        return "noop", None  # duplicate: nothing new stored

    result = _invoke(save, {"text": "I am married to Viviana"})
    assert result.ok
    assert result.output == {"op": "noop", "text": "I am married to Viviana"}


def test_empty_text_fails_closed_without_saving() -> None:
    async def save(text: str, kind: str) -> tuple[str, MemoryItem | None]:
        raise AssertionError("must not be called for empty text")

    result = _invoke(save, {"text": "   "})
    assert not result.ok and "required" in (result.error or "")


def test_save_failure_fails_closed() -> None:
    async def save(text: str, kind: str) -> tuple[str, MemoryItem | None]:
        raise RuntimeError("store down")

    result = _invoke(save, {"text": "remember me"})
    assert not result.ok and "could not save memory" in (result.error or "")


def test_manifest_is_low_risk_with_no_egress() -> None:
    # A memory write touches only the user's own store: no approval, no network.
    assert REMEMBER_MANIFEST.name == "remember"
    assert REMEMBER_MANIFEST.egress == ()
    assert REMEMBER_MANIFEST.permissions == ()
