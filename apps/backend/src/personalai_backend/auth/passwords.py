"""argon2id password hashing (ADR-0010 / OWASP Password Storage / RFC 9106).

Uses the OWASP "second" (CPU-light) profile: m=19456 KiB, t=2, p=1. Stores/returns the PHC string;
``verify_password`` is fail-closed (returns False on mismatch or a malformed hash, never raises).
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def hash_password(password: str) -> str:
    """Return an argon2id PHC string for ``password``."""
    return _HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Return True iff ``password`` matches ``password_hash`` (False on mismatch/bad hash)."""
    try:
        return _HASHER.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
