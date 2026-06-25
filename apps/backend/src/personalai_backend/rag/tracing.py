"""Force-disable LangSmith / LangChain tracing at process startup (#420 CISO review).

``langchain-core`` pulls ``langsmith`` transitively. LangSmith tracing is opt-in -- it only emits
when ``LANGCHAIN_TRACING_V2``/``LANGSMITH_TRACING`` is truthy AND an API key is set. The repo never
sets those, so the baseline is clean. But PersonalAI's in-process egress guard
(``assert_egress_allowed``) is a *voluntary* assertion; ``langsmith``'s own httpx client would NOT
call it, so the egress guard does NOT contain LangSmith. Containment relies on the env staying
disabled. We therefore defensively force the tracing flags off at startup so an inherited
environment can never silently enable a non-loopback egress to the LangSmith API.

Idempotent and side-effect-only on the environment; called from ``create_app`` so it runs for every
boot (and is exercised by tests, unlike the ``# pragma: no cover`` entrypoint).
"""

from __future__ import annotations

import os

# Truthy values LangSmith/LangChain accept for the tracing flags. If an inherited env set any of
# these we overwrite to "false"; otherwise we still set "false" so the flag is explicit.
_TRACING_FLAGS = ("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING", "LANGCHAIN_TRACING")

# Endpoint / API-key vars that would point tracing at a remote collector. Dropped defensively so a
# stray value cannot direct egress off-box even if a flag were later flipped on.
_TRACING_ENDPOINT_VARS = (
    "LANGCHAIN_ENDPOINT",
    "LANGSMITH_ENDPOINT",
    "LANGCHAIN_API_KEY",
    "LANGSMITH_API_KEY",
)


def disable_langchain_tracing() -> None:
    """Force LangSmith/LangChain tracing off and drop its endpoint/api-key env (#420)."""
    for flag in _TRACING_FLAGS:
        os.environ[flag] = "false"
    for var in _TRACING_ENDPOINT_VARS:
        os.environ.pop(var, None)
