"""Verifier verdict for the verification ladder (M8.2, #261).

The LLM-judge tier of the ladder returns this structured verdict (via ``generate_structured``), so
the graph can route on it deterministically instead of parsing free text. ``pass`` finalizes;
``needs_revision``/``fail`` can send the researcher back for a bounded retry (accurate mode only).
"""

from __future__ import annotations

from typing import Literal

from personalai_contracts.schemas.base import StrictModel


class Verdict(StrictModel):
    """A structured judgment of a draft answer against the user's request (internal to the verifier;
    not a versioned wire contract). ``generate_structured`` validates the judge's output."""

    verdict: Literal["pass", "needs_revision", "fail"]
    reason: str
    grounded: bool = True  # whether the answer is supported by the provided sources/tools
