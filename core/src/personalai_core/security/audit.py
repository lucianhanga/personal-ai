"""Append-only audit log (THREAT-MODEL: auditability).

Records security-relevant events (tool calls, egress decisions, approvals, model routing) as an
append-only sequence. Event payloads are passed through :func:`redact` so secrets never land in
the log. An optional file sink appends one JSON object per line (JSONL); entries are never
modified or deleted in place.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from personalai_contracts.ports import SecurityContext
from personalai_core.security.redaction import redact

# Conversation in scope for the current request; audit + app-log entries are stamped with it so the
# UI can show per-chat history. Set/reset by the backend around a chat turn (default None).
current_conversation: ContextVar[str | None] = ContextVar("current_conversation", default=None)

# Authenticated principal + tenant for the current request (ADR-0010). Set by the SecurityContext
# resolver; read by tenant-scoped data access, the audit log, the agent loop, and the MCP manager.
# Fail-closed: None means no authenticated request in scope.
current_security: ContextVar[SecurityContext | None] = ContextVar("current_security", default=None)


class SecurityContextError(RuntimeError):
    """A tenant-scoped operation ran with no SecurityContext in scope (fail-closed)."""


def require_security() -> SecurityContext:
    """Return the request's SecurityContext, or raise (fail-closed). Use at orchestration/agent
    boundaries that must be tenant-scoped instead of silently proceeding without a tenant."""
    ctx = current_security.get()
    if ctx is None:
        raise SecurityContextError("no security context in scope")
    return ctx


class AuditEvent(BaseModel):
    """A single audit record. Immutable; the payload is stored already-redacted."""

    model_config = ConfigDict(frozen=True)

    type: str
    actor: str | None = None
    payload: Mapping[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    conversation: str | None = None


class AuditLog:
    """An append-only audit log with an in-memory record and an optional JSONL file sink."""

    def __init__(self, sink_path: Path | None = None) -> None:
        self._entries: list[AuditEvent] = []
        self._sink_path = sink_path
        if sink_path is not None:
            # Create the sink with owner-only perms (audit data may reference sensitive context).
            sink_path.parent.mkdir(parents=True, exist_ok=True)
            if not sink_path.exists():
                os.close(os.open(sink_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600))

    def append(
        self, event_type: str, payload: Mapping[str, Any] | None = None, actor: str | None = None
    ) -> AuditEvent:
        """Append a redacted event. Returns the stored event."""
        event = AuditEvent(
            type=event_type,
            actor=actor,
            payload=redact(payload or {}),
            conversation=current_conversation.get(),
        )
        self._entries.append(event)
        if self._sink_path is not None:
            with self._sink_path.open("a", encoding="utf-8") as fh:
                fh.write(event.model_dump_json() + "\n")
        return event

    def entries(self) -> tuple[AuditEvent, ...]:
        """Return all recorded events in append order (read-only)."""
        return tuple(self._entries)
