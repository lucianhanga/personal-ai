"""Relational store for conversation history (ADR-0005).

Conversation content is user data and is stored verbatim; secret redaction applies to the
logging/audit path, not to the user's own messages.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import asyncpg


@dataclass(frozen=True)
class Conversation:
    """A chat thread."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Message:
    """A single turn within a conversation."""

    id: int
    conversation_id: str
    role: str
    content: str
    created_at: datetime


class PgConversationStore:
    """CRUD for conversations + their messages."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(self, *, id: str, title: str) -> Conversation:
        row = await self._pool.fetchrow(
            "INSERT INTO conversations (id, title) VALUES ($1, $2) "
            "RETURNING id, title, created_at, updated_at",
            id,
            title,
        )
        assert row is not None
        return _to_conversation(row)

    async def list(self) -> Sequence[Conversation]:
        rows = await self._pool.fetch(
            "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
        )
        return [_to_conversation(r) for r in rows]

    async def get(self, conversation_id: str) -> Conversation | None:
        row = await self._pool.fetchrow(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE id = $1",
            conversation_id,
        )
        return _to_conversation(row) if row is not None else None

    async def delete(self, conversation_id: str) -> None:
        await self._pool.execute("DELETE FROM conversations WHERE id = $1", conversation_id)

    async def add_message(self, *, conversation_id: str, role: str, content: str) -> Message:
        row = await self._pool.fetchrow(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1, $2, $3) "
            "RETURNING id, conversation_id, role, content, created_at",
            conversation_id,
            role,
            content,
        )
        assert row is not None
        await self._pool.execute(
            "UPDATE conversations SET updated_at = now() WHERE id = $1", conversation_id
        )
        return _to_message(row)

    async def list_messages(self, conversation_id: str) -> Sequence[Message]:
        rows = await self._pool.fetch(
            "SELECT id, conversation_id, role, content, created_at "
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
    )


def _to_message(row: asyncpg.Record) -> Message:
    return Message(
        id=row["id"],
        conversation_id=row["conversation_id"],
        role=row["role"],
        content=row["content"],
        created_at=row["created_at"],
    )
