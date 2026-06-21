"""In-memory ring buffer of recent application logs, surfaced via the API for the UI.

Captures PersonalAI's own logs (``personalai.*``) plus any WARNING+ from anywhere, so the Logs
panel shows what the backend is doing without the noise of access logs. Operational only — secrets
are never placed in free-text log messages (THREAT-MODEL); the endpoint is loopback + token-gated.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import UTC, datetime
from types import TracebackType
from typing import Any

from personalai_core.security import current_conversation


def _raw_line_from_traceback(tb: TracebackType | None) -> str | None:
    """Walk a traceback for the MCP stdio reader's ``line`` local: the unparseable stdout line."""
    while tb is not None:
        value = tb.tb_frame.f_locals.get("line")
        if isinstance(value, str):
            return value
        tb = tb.tb_next
    return None


class McpStdioLineFilter(logging.Filter):
    """Surface the raw offending line when the MCP stdio client fails to parse a server message.

    The MCP SDK (``mcp.client.stdio``) logs a generic ``Failed to parse JSONRPC message from
    server`` and discards the bad line, so the culprit server is unidentifiable. This filter
    recovers the line from the exception's traceback frame locals and appends it to the message, so
    the next occurrence names itself (a Node deprecation banner, a Python traceback, a Docker
    progress line, ...). Mutating the record means the enriched message reaches every handler.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info and "Failed to parse JSONRPC" in record.getMessage():
            raw = _raw_line_from_traceback(record.exc_info[2])
            if raw is not None:
                record.msg = f"{record.getMessage()} | raw stdout line: {raw!r}"
                record.args = ()
        return True


class RingBufferHandler(logging.Handler):
    """A logging handler that keeps the most recent records in memory."""

    def __init__(self, capacity: int = 500) -> None:
        super().__init__()
        self.records: deque[dict[str, Any]] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        # Keep our own logs and anything warning-or-worse; drop low-level library noise.
        if not record.name.startswith("personalai") and record.levelno < logging.WARNING:
            return
        self.records.append(
            {
                "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                # Tag with the active chat (if any) so the UI can filter per conversation.
                "conversation": current_conversation.get(),
            }
        )


LOG_BUFFER = RingBufferHandler()
_MCP_LINE_FILTER = McpStdioLineFilter()


def install() -> None:
    """Attach the shared buffer to the root logger once (idempotent)."""
    root = logging.getLogger()
    if LOG_BUFFER not in root.handlers:
        root.addHandler(LOG_BUFFER)
        if root.level == logging.NOTSET or root.level > logging.INFO:
            root.setLevel(logging.INFO)
    # Enrich MCP stdio parse errors with the raw offending line (runs before the record propagates
    # to the buffer), so an intermittent bad-server line names itself the next time it occurs.
    mcp_stdio = logging.getLogger("mcp.client.stdio")
    if _MCP_LINE_FILTER not in mcp_stdio.filters:
        mcp_stdio.addFilter(_MCP_LINE_FILTER)
