"""Redact secrets from data before it is logged or audited (THREAT-MODEL: secret leakage).

Secrets must never appear in prompts or logs. :func:`redact` recursively masks the values of
sensitive-looking keys in mappings/sequences so audit entries and log lines are safe to persist.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

REDACTED = "***"
MAX_DEPTH = 64
_TOO_DEEP = "<max-depth-exceeded>"
# Cap how long any single string we log/audit can be (huge tool args bloat + may hide secrets).
MAX_STR_LEN = 2000

# Mask secrets that appear inside free text (URLs, headers), not just sensitive keys.
_VALUE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"), r"\1" + REDACTED),  # Authorization: Bearer xxx
    (  # secret-looking URL query params: ?api_key=, &token=, &key=, &password=, &secret=
        re.compile(
            r"(?i)([?&](?:api[_-]?key|access_token|auth_token|token|key|password|secret)=)[^&\s]+"
        ),
        r"\1" + REDACTED,
    ),
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"), REDACTED),  # OpenAI-style
    (re.compile(r"\btvly-[A-Za-z0-9\-]{8,}\b"), REDACTED),  # Tavily
    (re.compile(r"\bgh[posru]_[A-Za-z0-9]{20,}\b"), REDACTED),  # GitHub PAT
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED),  # AWS access key id
    (re.compile(r"\beyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), REDACTED),  # JWT
)


def _redact_text(text: str) -> str:
    """Mask secret-shaped substrings in free text, then cap length."""
    for pattern, repl in _VALUE_PATTERNS:
        text = pattern.sub(repl, text)
    if len(text) > MAX_STR_LEN:
        text = text[:MAX_STR_LEN] + "...<truncated>"
    return text


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

    Mappings become plain dicts; sequences (except str/bytes) become lists. Values of sensitive
    keys are masked entirely; other strings are passed through value-level redaction that masks
    secret-shaped substrings (Bearer tokens, URL secret params, sk-/tvly-/ghp_/AKIA keys, JWTs) and
    caps length at :data:`MAX_STR_LEN`. Recursion is bounded by :data:`MAX_DEPTH` so an adversarial
    deeply-nested payload cannot crash the audit path; deeper substructures are replaced with a
    sentinel.
    """
    if _depth > MAX_DEPTH:
        return _TOO_DEEP
    if isinstance(value, Mapping):
        return {
            key: (REDACTED if _is_sensitive(str(key)) else redact(val, _depth=_depth + 1))
            for key, val in value.items()
        }
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, bytes):
        return value
    if isinstance(value, Sequence):
        return [redact(item, _depth=_depth + 1) for item in value]
    return value
