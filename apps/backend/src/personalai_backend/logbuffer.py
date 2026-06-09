"""In-memory ring buffer of recent application logs, surfaced via the API for the UI.

Captures PersonalAI's own logs (``personalai.*``) plus any WARNING+ from anywhere, so the Logs
panel shows what the backend is doing without the noise of access logs. Operational only — secrets
are never placed in free-text log messages (THREAT-MODEL); the endpoint is loopback + token-gated.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import UTC, datetime
from typing import Any


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
            }
        )


LOG_BUFFER = RingBufferHandler()


def install() -> None:
    """Attach the shared buffer to the root logger once (idempotent)."""
    root = logging.getLogger()
    if LOG_BUFFER not in root.handlers:
        root.addHandler(LOG_BUFFER)
        if root.level == logging.NOTSET or root.level > logging.INFO:
            root.setLevel(logging.INFO)
