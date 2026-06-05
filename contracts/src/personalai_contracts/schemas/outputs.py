"""Structured-output result and error/repair envelopes (ADR-0003).

Every model/tool output is validated at a boundary. ``StructuredResult`` is the normalized
success/failure envelope. When validation fails, a ``RepairRequest`` carries the invalid
payload and the validation errors back to the producer for a bounded repair retry; if repair
fails the system fails closed (the consumer never executes an unvalidated payload).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from pydantic import Field, model_validator

from personalai_contracts.schemas.base import StrictModel, VersionedModel


class ErrorInfo(StrictModel):
    """A structured error."""

    code: str
    message: str
    details: Mapping[str, Any] = Field(default_factory=dict)


class StructuredResult(VersionedModel):
    """A normalized result envelope: exactly one of ``data`` (ok) or ``error`` (not ok)."""

    SCHEMA_ID: ClassVar[str] = "personalai.output.result"
    SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    ok: bool
    data: Mapping[str, Any] | None = None
    error: ErrorInfo | None = None
    schema_version: str = Field(default=SCHEMA_VERSION)

    @model_validator(mode="after")
    def _check_consistency(self) -> StructuredResult:
        if self.ok and self.error is not None:
            raise ValueError("ok result must not carry an error")
        if not self.ok and self.error is None:
            raise ValueError("failed result must carry an error")
        return self


class RepairRequest(VersionedModel):
    """The structured input to a bounded repair retry of an invalid payload."""

    SCHEMA_ID: ClassVar[str] = "personalai.output.repair_request"
    SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    schema_id: str
    target_version: str
    invalid_payload: Mapping[str, Any]
    errors: Sequence[str]
    attempt: int = Field(ge=1, description="1-based attempt counter; bounded by the caller.")
    schema_version: str = Field(default=SCHEMA_VERSION)
