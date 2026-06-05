"""Versioned schema registry (ADR-0003).

Registers :class:`VersionedModel` contracts by their ``SCHEMA_ID`` + semver and validates
payloads against a requested version. The registry supports the current major version (N) and
the previous major (N-1); requests for unsupported or unknown schemas/versions fail closed, as
does any payload that does not validate.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from personalai_contracts.schemas.base import VersionedModel, parse_semver


class SchemaError(Exception):
    """Raised when a schema id/version is unknown or unsupported (fail-closed)."""


class SchemaValidationError(Exception):
    """Raised when a payload does not validate against its schema (fail-closed)."""

    def __init__(self, schema_id: str, version: str, errors: list[str]) -> None:
        self.schema_id = schema_id
        self.version = version
        self.errors = errors
        super().__init__(f"{schema_id}@{version} validation failed: {errors}")


class SchemaRegistry:
    """A registry of versioned contracts supporting the N and N-1 major versions."""

    def __init__(self) -> None:
        self._by_id: dict[str, dict[str, type[VersionedModel]]] = {}

    def register(self, model: type[VersionedModel]) -> None:
        """Register a versioned contract by its ``SCHEMA_ID`` and ``SCHEMA_VERSION``."""
        parse_semver(model.SCHEMA_VERSION)  # validate format, fail fast
        self._by_id.setdefault(model.SCHEMA_ID, {})[model.SCHEMA_VERSION] = model

    def get(self, schema_id: str, version: str) -> type[VersionedModel] | None:
        """Return the model class for ``schema_id`` at ``version``, or None."""
        return self._by_id.get(schema_id, {}).get(version)

    def supported_majors(self, schema_id: str) -> tuple[int, ...]:
        """The current (N) and previous (N-1) major versions registered for ``schema_id``."""
        versions = self._by_id.get(schema_id)
        if not versions:
            return ()
        majors = sorted({parse_semver(v).major for v in versions}, reverse=True)
        return tuple(majors[:2])

    def is_supported(self, schema_id: str, version: str) -> bool:
        """Whether ``version`` is registered and in a supported (N or N-1) major line."""
        if self.get(schema_id, version) is None:
            return False
        # A registered version was validated at register() time, so parsing is safe here.
        major = parse_semver(version).major
        return major in self.supported_majors(schema_id)

    def validate(self, schema_id: str, version: str, payload: Mapping[str, Any]) -> VersionedModel:
        """Validate ``payload`` against ``schema_id@version``. Fail-closed on any problem."""
        if schema_id not in self._by_id:
            raise SchemaError(f"unknown schema id: {schema_id!r}")
        if not self.is_supported(schema_id, version):
            raise SchemaError(
                f"unsupported version {version!r} for {schema_id!r} "
                f"(supported majors: {self.supported_majors(schema_id)})"
            )
        model = self.get(schema_id, version)
        assert model is not None  # guaranteed by is_supported
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise SchemaValidationError(schema_id, version, [str(e) for e in exc.errors()]) from exc


# The built-in contracts registered by default. Importing here keeps the registry as the one
# place that knows the full set; it does not create import cycles (all are in this package).
def _builtin_models() -> list[type[VersionedModel]]:
    from personalai_contracts.schemas.messages import AgentMessage
    from personalai_contracts.schemas.outputs import RepairRequest, StructuredResult
    from personalai_contracts.schemas.tools import ToolInvocation, ToolManifest

    return [AgentMessage, ToolInvocation, ToolManifest, StructuredResult, RepairRequest]


def default_registry() -> SchemaRegistry:
    """A registry pre-populated with all built-in PersonalAI contracts."""
    registry = SchemaRegistry()
    for model in _builtin_models():
        registry.register(model)
    return registry
