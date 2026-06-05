"""Redact secrets from data before it is logged or audited (THREAT-MODEL: secret leakage).

Secrets must never appear in prompts or logs. :func:`redact` recursively masks the values of
sensitive-looking keys in mappings/sequences so audit entries and log lines are safe to persist.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

REDACTED = "***"
MAX_DEPTH = 64
_TOO_DEEP = "<max-depth-exceeded>"

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
    "passphrase",
    "secret",
    "credential",
    "cookie",
    "private_key",
    "bearer",
    "session",
    "signature",
    "connection_string",
    "dsn",
)


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def redact(value: Any, *, _depth: int = 0) -> Any:
    """Return a copy of ``value`` with sensitive mapping values masked, recursively.

    Mappings become plain dicts; sequences (except str/bytes) become lists. Scalars are returned
    unchanged (only the *values of sensitive keys* are masked, not arbitrary strings). Recursion is
    bounded by :data:`MAX_DEPTH` so an adversarial deeply-nested payload cannot crash the audit
    path; deeper substructures are replaced with a sentinel. Value-level masking of secrets that
    appear inside free-text strings/URLs is a follow-up (M1).
    """
    if _depth > MAX_DEPTH:
        return _TOO_DEEP
    if isinstance(value, Mapping):
        return {
            key: (REDACTED if _is_sensitive(str(key)) else redact(val, _depth=_depth + 1))
            for key, val in value.items()
        }
    if isinstance(value, str | bytes):
        return value
    if isinstance(value, Sequence):
        return [redact(item, _depth=_depth + 1) for item in value]
    return value
