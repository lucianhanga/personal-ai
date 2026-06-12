"""Relational store for conversation history (ADR-0005).

Conversation content is user data and is stored verbatim; secret redaction applies to the
logging/audit path, not to the user's own messages.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg

from personalai_storage_postgres.db import TENANT_ID_SQL, Querier


@dataclass(frozen=True)
class Conversation:
    """A chat thread."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    summary: str | None = None
    summary_through: int = 0
    incognito: bool = False


@dataclass(frozen=True)
class Message:
    """A single turn within a conversation."""

    id: int
    conversation_id: str
    role: str
    content: str
    created_at: datetime
    meta: Mapping[str, Any] | None = None  # tool steps + reasoning, for the UI details view


class PgConversationStore:
    """CRUD for conversations + their messages."""

    def __init__(self, pool: Querier) -> None:
        self._pool = pool

    _COLS = "id, title, created_at, updated_at, summary, summary_through, incognito"

    async def create(self, *, id: str, title: str, incognito: bool = False) -> Conversation:
        row = await self._pool.fetchrow(
            f"INSERT INTO conversations (id, title, incognito, tenant_id) "
            f"VALUES ($1, $2, $3, {TENANT_ID_SQL}) RETURNING {self._COLS}",
            id,
            title,
            incognito,
        )
        assert row is not None
        return _to_conversation(row)

    async def list(self) -> Sequence[Conversation]:
        rows = await self._pool.fetch(
            f"SELECT {self._COLS} FROM conversations ORDER BY updated_at DESC"
        )
        return [_to_conversation(r) for r in rows]

    async def get(self, conversation_id: str) -> Conversation | None:
        row = await self._pool.fetchrow(
            f"SELECT {self._COLS} FROM conversations WHERE id = $1", conversation_id
        )
        return _to_conversation(row) if row is not None else None

    async def update_summary(
        self, conversation_id: str, *, summary: str, summary_through: int
    ) -> None:
        await self._pool.execute(
            "UPDATE conversations SET summary = $2, summary_through = $3 WHERE id = $1",
            conversation_id,
            summary,
            summary_through,
        )

    async def rename(self, conversation_id: str, *, title: str) -> None:
        await self._pool.execute(
            "UPDATE conversations SET title = $2, updated_at = now() WHERE id = $1",
            conversation_id,
            title,
        )

    async def delete(self, conversation_id: str) -> None:
        await self._pool.execute("DELETE FROM conversations WHERE id = $1", conversation_id)

    async def add_message(
        self,
        *,
        conversation_id: str,
        role: str,
        content: str,
        meta: Mapping[str, Any] | None = None,
    ) -> Message:
        # Single statement (CTE) so the message insert + the conversation updated_at bump are atomic
        # even when the store runs on a per-query connection (TenantQuerier) — previously two
        # separate statements could half-apply (audit A3/#226).
        row = await self._pool.fetchrow(
            f"WITH ins AS ("
            f"  INSERT INTO messages (conversation_id, role, content, meta, tenant_id) "
            f"  VALUES ($1, $2, $3, $4, {TENANT_ID_SQL}) "
            f"  RETURNING id, conversation_id, role, content, created_at, meta"
            f"), upd AS ("
            f"  UPDATE conversations SET updated_at = now() WHERE id = $1"
            f") SELECT id, conversation_id, role, content, created_at, meta FROM ins",
            conversation_id,
            role,
            content,
            json.dumps(meta) if meta else None,
        )
        assert row is not None
        return _to_message(row)

    async def list_messages(self, conversation_id: str) -> Sequence[Message]:
        rows = await self._pool.fetch(
            "SELECT id, conversation_id, role, content, created_at, meta "
            "FROM messages WHERE conversation_id = $1 ORDER BY id",
            conversation_id,
        )
        return [_to_message(r) for r in rows]


def _to_conversation(row: asyncpg.Record) -> Conversation:
    return Conversation(
        id=row["id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        summary=row["summary"],
        summary_through=row["summary_through"],
        incognito=row["incognito"],
    )


def _to_message(row: asyncpg.Record) -> Message:
    raw_meta = row.get("meta")
    return Message(
        id=row["id"],
        conversation_id=row["conversation_id"],
        role=row["role"],
        content=row["content"],
        created_at=row["created_at"],
        # asyncpg returns jsonb as a string unless a codec is set; decode defensively.
        meta=json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta,
    )
