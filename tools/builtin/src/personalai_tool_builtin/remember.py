"""A tool that writes a durable fact to long-term memory (M4) when the user asks to remember it.

Without this, "remember that ..." had no grounding: the agent could only *claim* it saved a memory
while the actual store is populated by a separate, non-deterministic background extraction. This
tool makes the write real and explicit — the agent calls it, the fact is consolidated into memory
(dedup + conflict reconciliation, #310), and the confirmation is backed by the tool result (and
shows in the trace). The consolidation is injected so this tool stays decoupled from core; it
depends only on contracts.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from personalai_contracts.ports import MemoryItem, ToolCall, ToolResult
from personalai_contracts.schemas.tools import Provenance, RiskLevel, ToolManifest

# Save (text, kind) into long-term memory, returning (op, stored_item). op is "add" | "update" |
# "noop"; item is the stored/updated memory, or None for a noop (already remembered).
SaveMemory = Callable[[str, str], Awaitable[tuple[str, MemoryItem | None]]]

REMEMBER_MANIFEST = ToolManifest(
    name="remember",
    version="1.0.0",
    provenance=Provenance(maintainer="PersonalAI", license="Apache-2.0"),
    description=(
        "Save a durable fact, preference, or detail about the user to long-term memory when they "
        "ask you to remember something (e.g. 'remember that I am married to ...'). Persists the "
        "memory and returns the result. Only use it for stable, user-specific information worth "
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
        "properties": {
            "op": {"type": "string"},
            "id": {"type": "string"},
            "text": {"type": "string"},
        },
        "required": ["op"],
    },
    egress=(),
    risk=RiskLevel.LOW,
)


class RememberTool:
    """Persist a user-stated fact to long-term memory via the injected consolidation function."""

    name = "remember"

    def __init__(self, save: SaveMemory) -> None:
        self._save = save

    async def invoke(self, call: ToolCall) -> ToolResult:
        text = str(call.args.get("text", "")).strip()
        if not text:
            return ToolResult(ok=False, error="nothing to remember: 'text' is required")
        kind = str(call.args.get("kind", "semantic"))
        try:
            op, item = await self._save(text, kind)
        except Exception as exc:  # noqa: BLE001 - fail closed; a tool must never raise to the agent
            return ToolResult(ok=False, error=f"could not save memory: {exc}")
        if op == "noop":
            # Already captured by an existing memory — truthful "nothing new to store".
            return ToolResult(ok=True, output={"op": "noop", "text": text})
        if item is None:
            return ToolResult(ok=False, error="could not save memory")
        # op is "add" (new) or "update" (replaced a contradicting memory).
        return ToolResult(ok=True, output={"op": op, "id": item.id, "text": item.text})
