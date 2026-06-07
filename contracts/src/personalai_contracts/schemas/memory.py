"""Structured-output schema for long-term memory extraction (M4-2).

Plain ``StrictModel`` (not a versioned/registered contract), used to constrain the model's fact
extraction to validated JSON. Kept decoupled from the storage port (uses a literal for ``kind``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from personalai_contracts.schemas.base import StrictModel


class ExtractedFact(StrictModel):
    """A single candidate long-term memory extracted from a conversation."""

    kind: Literal["semantic", "episodic", "preference"]
    text: str
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class ExtractionResult(StrictModel):
    """The set of facts worth remembering (possibly empty)."""

    facts: list[ExtractedFact] = Field(default_factory=list)
