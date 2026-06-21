"""A tool that writes a durable fact to long-term memory (M4) when the user asks to remember it.

Without this, "remember that ..." had no grounding: the agent could only *claim* it saved a memory
while the actual store is populated by a separate, non-deterministic background extraction. This
tool makes the write real and explicit — the agent calls it, a `MemoryItem` is persisted, and the
confirmation is backed by the tool result (and shows in the trace). Depends only on contracts ports.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence

from personalai_contracts.ports import ToolCall, ToolResult
from personalai_contracts.ports.storage import MemoryKind, MemoryStore
from personalai_contracts.schemas.tools import Provenance, RiskLevel, ToolManifest

# Embed one string to a vector. Injected so this tool stays decoupled from any concrete provider.
EmbedText = Callable[[str], Awaitable[Sequence[float]]]

REMEMBER_MANIFEST = ToolManifest(
    name="remember",
    version="1.0.0",
    provenance=Provenance(maintainer="PersonalAI", license="Apache-2.0"),
    description=(
        "Save a durable fact, preference, or detail about the user to long-term memory when they "
        "ask you to remember something (e.g. 'remember that I am married to ...'). Persists the "
        "memory and returns its id. Only use it for stable, user-specific information worth "
        "recalling in future chats — not transient details. Do not claim to have saved a memory "
        "unless this tool returned ok."
    ),
    capabilities=["memory.write"],
    permissions=(),
    inputs={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The fact to remember, as one concise self-contained statement.",
            },
            "kind": {
                "type": "string",
                "enum": ["semantic", "episodic", "preference"],
                "description": "semantic = a fact, preference = how the user likes things, "
                "episodic = an event. Defaults to semantic.",
            },
        },
        "required": ["text"],
    },
    outputs={
        "type": "object",
        "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
        "required": ["id", "text"],
    },
    egress=(),
    risk=RiskLevel.LOW,
)


class RememberTool:
    """Persist a user-stated fact to long-term memory. The write is tenant-scoped by the store."""

    name = "remember"

    def __init__(self, store: MemoryStore, embed: EmbedText) -> None:
        self._store = store
        self._embed = embed

    async def invoke(self, call: ToolCall) -> ToolResult:
        text = str(call.args.get("text", "")).strip()
        if not text:
            return ToolResult(ok=False, error="nothing to remember: 'text' is required")
        try:
            kind = MemoryKind(str(call.args.get("kind", "semantic")))
        except ValueError:
            kind = MemoryKind.SEMANTIC
        try:
            embedding = await self._embed(text)
        except Exception as exc:  # noqa: BLE001 - fail closed; a tool must never raise to the agent
            return ToolResult(ok=False, error=f"could not embed memory: {exc}")
        if not embedding:
            return ToolResult(ok=False, error="could not embed memory: empty vector")
        item = await self._store.add(
            id=str(uuid.uuid4()),
            kind=kind,
            text=text,
            embedding=embedding,
            confidence=1.0,  # the user stated it directly, so it is certain
            source={"origin": "user_request"},
        )
        return ToolResult(ok=True, output={"id": item.id, "text": item.text})
