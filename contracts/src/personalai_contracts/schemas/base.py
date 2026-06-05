"""Schema foundations: strict, versioned Pydantic models (ADR-0003).

All structured-output contracts derive from :class:`StrictModel`, which is fail-closed
(``extra="forbid"``) and immutable (``frozen=True``). Versioned contracts add a stable
``SCHEMA_ID`` and a semver ``SCHEMA_VERSION`` so they can be registered and validated
against a requested version (see :mod:`personalai_contracts.schemas.registry`).
"""

from __future__ import annotations

import re
from typing import ClassVar, NamedTuple

from pydantic import BaseModel, ConfigDict

_SEMVER_RE = re.compile(r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$")


class SemVer(NamedTuple):
    """A parsed semantic version."""

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_semver(version: str) -> SemVer:
    """Parse ``major.minor.patch`` into a :class:`SemVer`, raising ``ValueError`` if invalid."""
    match = _SEMVER_RE.match(version)
    if match is None:
        raise ValueError(f"invalid semantic version: {version!r}")
    return SemVer(
        major=int(match["major"]),
        minor=int(match["minor"]),
        patch=int(match["patch"]),
    )


class StrictModel(BaseModel):
    """Base for all contracts: rejects unknown fields (fail-closed) and is immutable."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        validate_assignment=True,
    )


class VersionedModel(StrictModel):
    """A contract with a stable identity and a semantic version.

    Subclasses MUST set both class variables; the registry uses them to register and to
    resolve the supported (N and N-1) versions of a schema.
    """

    SCHEMA_ID: ClassVar[str]
    SCHEMA_VERSION: ClassVar[str]
