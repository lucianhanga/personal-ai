"""A safe arithmetic calculator tool (no code execution).

Evaluates a restricted arithmetic AST — numbers and +, -, *, /, //, %, ** only. Names, calls,
attributes, etc. are rejected, so there is no path to arbitrary code (LOW risk, no permissions).
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable

from personalai_contracts.ports import ToolCall, ToolResult
from personalai_contracts.schemas.tools import Provenance, RiskLevel, ToolManifest

_BIN: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

CALCULATOR_MANIFEST = ToolManifest(
    name="calculator",
    version="1.0.0",
    provenance=Provenance(maintainer="PersonalAI", license="Apache-2.0"),
    capabilities=["arithmetic"],
    permissions=(),
    inputs={
        "type": "object",
        "properties": {"expression": {"type": "string"}},
        "required": ["expression"],
    },
    outputs={
        "type": "object",
        "properties": {"result": {"type": "number"}},
        "required": ["result"],
    },
    egress=(),
    risk=RiskLevel.LOW,
)


def _eval(node: ast.expr) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return _BIN[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported expression")


class Calculator:
    """Evaluate a safe arithmetic expression."""

    name = "calculator"

    async def invoke(self, call: ToolCall) -> ToolResult:
        expression = str(call.args.get("expression", ""))
        try:
            value = _eval(ast.parse(expression, mode="eval").body)
        except (ValueError, SyntaxError, ZeroDivisionError, TypeError, OverflowError) as exc:
            return ToolResult(ok=False, error=f"cannot evaluate: {exc}")
        return ToolResult(ok=True, output={"result": value})
