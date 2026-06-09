"""Single-agent tool-calling loop (M6-2).

The model is offered the registered tools; when it returns ``tool_calls``, each is executed through
the **Tool gateway** (so all permission/egress/schema/timeout/audit checks apply), the results are
fed back, and the loop repeats until the model produces a final answer or the iteration cap is hit.

Provider-agnostic: tool results are appended as a plain message, so it works the same on Ollama and
OpenAI-compatible providers. Tool output is untrusted data, not instructions.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from personalai_contracts.ports import (
    ChatMessage,
    GenerationRequest,
    ModelProvider,
    Role,
    ToolCall,
    ToolSpec,
)
from personalai_contracts.schemas.tools import Permission
from personalai_core.gateway import RegisteredTool, ToolGateway


@dataclass(frozen=True)
class AgentEvent:
    """A step in the agent loop: a tool call, its result, or the final answer."""

    type: Literal["tool_call", "tool_result", "final"]
    tool: str | None = None
    args: Mapping[str, Any] | None = None
    ok: bool | None = None
    output: Mapping[str, Any] | None = None
    error: str | None = None
    answer: str | None = None


async def run_agent(
    *,
    messages: Sequence[ChatMessage],
    provider: ModelProvider,
    model: str,
    gateway: ToolGateway,
    tools: Sequence[RegisteredTool],
    grants: Sequence[Permission] = (),
    approved: bool = False,
    max_iterations: int = 4,
) -> AsyncIterator[AgentEvent]:
    """Drive the model<->gateway tool-calling loop, yielding events as they happen."""
    convo = list(messages)
    specs = [
        ToolSpec(
            name=rt.manifest.name,
            description=rt.manifest.description,
            parameters=dict(rt.manifest.inputs),
        )
        for rt in tools
    ]
    versions = {rt.manifest.name: rt.manifest.version for rt in tools}

    text = ""
    for _ in range(max_iterations):
        result = await provider.generate(
            GenerationRequest(messages=convo, model=model, tools=specs or None)
        )
        text = result.text
        if not result.tool_calls:
            yield AgentEvent(type="final", answer=text)
            return

        # Echo the assistant's (possibly empty) turn, then each tool result as a TOOL-role message
        # so the model sees the call was answered (native protocol) and produces a final reply.
        if text.strip():
            convo.append(ChatMessage(Role.ASSISTANT, text))
        for call in result.tool_calls:
            yield AgentEvent(type="tool_call", tool=call.name, args=dict(call.arguments))
            tool_result = await gateway.invoke(
                ToolCall(call.name, versions.get(call.name, "1.0.0"), call.arguments),
                grants=grants,
                approved=approved,
            )
            yield AgentEvent(
                type="tool_result",
                tool=call.name,
                ok=tool_result.ok,
                output=dict(tool_result.output),
                error=tool_result.error,
            )
            payload = (
                json.dumps(dict(tool_result.output))
                if tool_result.ok
                else f"error: {tool_result.error}"
            )
            convo.append(ChatMessage(Role.TOOL, f"{call.name}: {payload}"))

    yield AgentEvent(
        type="final",
        answer=text or "I couldn't complete that within the tool-step limit.",
    )
