"""Calculator tool: correct arithmetic + no code execution."""

from __future__ import annotations

import asyncio

import pytest

from personalai_contracts.ports import ToolCall, ToolResult
from personalai_tool_builtin import Calculator


def _calc(expr: str) -> ToolResult:
    return asyncio.run(Calculator().invoke(ToolCall("calculator", "1.0.0", {"expression": expr})))


@pytest.mark.parametrize(
    ("expr", "expected"),
    [("2 + 3 * 4", 14.0), ("-(2 ** 3)", -8.0), ("7 // 2", 3.0), ("7 % 2", 1.0), ("10 / 4", 2.5)],
)
def test_evaluates_arithmetic(expr: str, expected: float) -> None:
    result = _calc(expr)
    assert result.ok and result.output["result"] == expected


@pytest.mark.parametrize("expr", ["__import__('os')", "a + 1", "len('x')", "1 if 1 else 2", "x.y"])
def test_rejects_non_arithmetic(expr: str) -> None:
    result = _calc(expr)
    assert not result.ok and "cannot evaluate" in (result.error or "")


def test_rejects_syntax_error_and_div_by_zero() -> None:
    assert not _calc("1 +").ok
    assert not _calc("1 / 0").ok
