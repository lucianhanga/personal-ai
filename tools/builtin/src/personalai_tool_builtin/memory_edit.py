"""Tools that let the agent correct or remove a long-term memory on request (#314).

`remember` only adds; when the user says "that's wrong, it's actually …" or "forget that", the agent
needs to edit an existing memory. These resolve *which* memory by semantic search (the agent rarely
knows ids) and then act: `update_memory` supersedes the matched memory and stores the correction;
`forget_memory` supersedes (hides) it. Both are reversible (superseded rows are kept, just hidden
from search/list) — so they are LOW risk. Depend only on contracts ports.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence

from personalai_contracts.ports import MemoryItem, MemoryStore, ToolCall, ToolResult
from personalai_contracts.schemas.tools import Provenance, RiskLevel, ToolManifest

# Embed one string to a vector (injected, so these stay decoupled from any concrete provider).
EmbedText = Callable[[str], Awaitable[Sequence[float]]]

# Below this similarity we refuse to act, rather than edit/delete the wrong memory.
RESOLVE_THRESHOLD = 0.5

UPDATE_MEMORY_MANIFEST = ToolManifest(
    name="update_memory",
    version="1.0.0",
    provenance=Provenance(maintainer="PersonalAI", license="Apache-2.0"),
    description=(
        "Correct an existing long-term memory. Describe the memory to change in `query` and give "
        "the corrected statement in `new_text`; the closest matching memory is replaced (the old "
        "one is superseded). Use this when the user corrects a fact you already remember."
    ),
    capabilities=["memory.write"],
    permissions=(),
    inputs={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A short description of the existing memory to correct.",
            },
            "new_text": {
                "type": "string",
                "description": "The corrected, self-contained statement to store instead.",
            },
        },
        "required": ["query", "new_text"],
    },
    outputs={
        "type": "object",
        "properties": {"updated_from": {"type": "string"}, "to": {"type": "string"}},
        "required": ["to"],
    },
    egress=(),
    risk=RiskLevel.LOW,
)

FORGET_MEMORY_MANIFEST = ToolManifest(
    name="forget_memory",
    version="1.0.0",
    provenance=Provenance(maintainer="PersonalAI", license="Apache-2.0"),
    description=(
        "Forget an existing long-term memory. Describe it in `query`; the closest matching memory "
        "is removed (hidden from future recall). Use this when the user asks you to forget it."
    ),
    capabilities=["memory.write"],
    permissions=(),
    inputs={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A short description of the memory to forget.",
            }
        },
        "required": ["query"],
    },
    outputs={
        "type": "object",
        "properties": {"forgotten": {"type": "string"}},
        "required": ["forgotten"],
    },
    egress=(),
    risk=RiskLevel.LOW,
)


async def _resolve(store: MemoryStore, embed: EmbedText, query: str) -> MemoryItem | None:
    """The single best-matching memory for ``query`` above the confidence floor, else None."""
    try:
        vector = await embed(query)
    except Exception:  # noqa: BLE001 - a tool must never raise to the agent; treat as no match
        return None
    matches = await store.search(vector, top_k=1)
    if not matches or (matches[0].score or 0.0) < RESOLVE_THRESHOLD:
        return None
    return matches[0]


class UpdateMemoryTool:
    """Replace the memory that best matches ``query`` with ``new_text`` (supersede + add)."""

    name = "update_memory"

    def __init__(self, store: MemoryStore, embed: EmbedText) -> None:
        self._store = store
        self._embed = embed

    async def invoke(self, call: ToolCall) -> ToolResult:
        query = str(call.args.get("query", "")).strip()
        new_text = str(call.args.get("new_text", "")).strip()
        if not query or not new_text:
            return ToolResult(ok=False, error="'query' and 'new_text' are required")
        target = await _resolve(self._store, self._embed, query)
        if target is None:
            return ToolResult(ok=False, error=f"no memory matching {query!r} to update")
        try:
            new_vec = await self._embed(new_text)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"could not embed the correction: {exc}")
        await self._store.supersede(target.id)
        item = await self._store.add(
            id=str(uuid.uuid4()),
            kind=target.kind,
            text=new_text,
            embedding=new_vec,
            confidence=1.0,
            source={"origin": "user_request"},
        )
        return ToolResult(ok=True, output={"updated_from": target.text, "to": item.text})


class ForgetMemoryTool:
    """Forget (supersede) the memory that best matches ``query``."""

    name = "forget_memory"

    def __init__(self, store: MemoryStore, embed: EmbedText) -> None:
        self._store = store
        self._embed = embed

    async def invoke(self, call: ToolCall) -> ToolResult:
        query = str(call.args.get("query", "")).strip()
        if not query:
            return ToolResult(ok=False, error="'query' is required: describe the memory to forget")
        target = await _resolve(self._store, self._embed, query)
        if target is None:
            return ToolResult(ok=False, error=f"no memory matching {query!r} to forget")
        await self._store.supersede(target.id)
        return ToolResult(ok=True, output={"forgotten": target.text})
