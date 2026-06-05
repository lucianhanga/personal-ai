"""Redact secrets from data before it is logged or audited (THREAT-MODEL: secret leakage).

Secrets must never appear in prompts or logs. :func:`redact` recursively masks the values of
sensitive-looking keys in mappings/sequences so audit entries and log lines are safe to persist.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

REDACTED = "***"

# Key names whose values are masked (compared case-insensitively, substring match).
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "auth_token",
    "token",
    "password",
    "passwd",
    "secret",
    "cookie",
    "private_key",
)


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def redact(value: Any) -> Any:
    """Return a copy of ``value`` with sensitive mapping values masked, recursively.

    Mappings become plain dicts; sequences (except str/bytes) become lists. Scalars are returned
    unchanged (only the *values of sensitive keys* are masked, not arbitrary strings).
    """
    if isinstance(value, Mapping):
        return {
            key: (REDACTED if _is_sensitive(str(key)) else redact(val))
            for key, val in value.items()
        }
    if isinstance(value, str | bytes):
        return value
    if isinstance(value, Sequence):
        return [redact(item) for item in value]
    return value
