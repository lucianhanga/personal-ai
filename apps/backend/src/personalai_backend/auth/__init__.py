"""Built-in authentication adapters (ADR-0010): argon2id passwords + the IdentityProvider."""

from personalai_backend.auth.builtin import BuiltinIdentityProvider
from personalai_backend.auth.passwords import hash_password, verify_password

__all__ = ["BuiltinIdentityProvider", "hash_password", "verify_password"]
