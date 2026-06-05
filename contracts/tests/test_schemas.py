"""Schema contracts: round-trips, fixture-driven validation, registry, and JSON Schema drift.

The fixtures under ``schemas/fixtures`` are shared with the TS/Zod tests so both bindings agree
on the same valid/invalid payloads (ADR-0003).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from personalai_contracts.schemas import (
    AgentMessage,
    SchemaError,
    SchemaRegistry,
    SchemaValidationError,
    StructuredResult,
    ToolInvocation,
    ToolManifest,
    default_registry,
    parse_semver,
)
from personalai_contracts.schemas.base import VersionedModel
from personalai_contracts.schemas.export import json_schemas, render

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "schemas" / "fixtures"
JSON_DIR = REPO_ROOT / "schemas" / "json"

# Fixture directory -> (schema_id, version).
FIXTURE_SCHEMAS = {
    "agent-message": ("personalai.agent.message", "1.0.0"),
    "tool-invocation": ("personalai.tool.invocation", "1.0.0"),
    "structured-result": ("personalai.output.result", "1.0.0"),
}


def _load(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return result


def _cases(kind: str) -> list[tuple[str, str, Path]]:
    cases: list[tuple[str, str, Path]] = []
    for fixture_dir, (schema_id, version) in FIXTURE_SCHEMAS.items():
        for validity in ("valid", "invalid"):
            for path in sorted((FIXTURES / fixture_dir / validity).glob("*.json")):
                if validity == kind:
                    cases.append((schema_id, version, path))
    return cases


# --------------------------------------------------------------------------- round-trips
def test_agent_message_round_trip() -> None:
    msg = AgentMessage.model_validate({"from": "a", "to": "b", "type": "ping"})
    assert msg.from_ == "a"
    dumped = msg.model_dump(by_alias=True)
    assert dumped["from"] == "a"
    assert AgentMessage.model_validate(dumped) == msg


def test_tool_invocation_and_manifest_round_trip() -> None:
    inv = ToolInvocation.model_validate({"tool": "t", "version": "1.0.0"})
    assert ToolInvocation.model_validate(inv.model_dump()) == inv

    manifest = ToolManifest.model_validate(
        {"name": "t", "version": "1.0.0", "provenance": {"maintainer": "me"}}
    )
    assert manifest.risk.value == "high"  # safe default
    assert tuple(manifest.egress) == ()  # deny egress by default


# --------------------------------------------------------------------------- fixture-driven
@pytest.mark.parametrize(("schema_id", "version", "path"), _cases("valid"))
def test_valid_fixtures_pass(schema_id: str, version: str, path: Path) -> None:
    registry = default_registry()
    model = registry.validate(schema_id, version, _load(path))
    assert schema_id == model.SCHEMA_ID


@pytest.mark.parametrize(("schema_id", "version", "path"), _cases("invalid"))
def test_invalid_fixtures_fail_closed(schema_id: str, version: str, path: Path) -> None:
    registry = default_registry()
    with pytest.raises(SchemaValidationError):
        registry.validate(schema_id, version, _load(path))


# --------------------------------------------------------------------------- registry
def test_structured_result_consistency() -> None:
    assert StructuredResult(ok=True, data={"x": 1}).ok is True
    with pytest.raises(SchemaValidationError):
        default_registry().validate(
            "personalai.output.result",
            "1.0.0",
            {"ok": True, "error": {"code": "c", "message": "m"}},
        )


def test_registry_unknown_and_unsupported() -> None:
    registry = default_registry()
    with pytest.raises(SchemaError):
        registry.validate("nope", "1.0.0", {})
    with pytest.raises(SchemaError):
        registry.validate(
            "personalai.agent.message", "9.9.9", {"from": "a", "to": "b", "type": "t"}
        )


def test_registry_supports_n_and_n_minus_1() -> None:
    class V1(VersionedModel):
        SCHEMA_ID = "x.test"
        SCHEMA_VERSION = "1.0.0"

    class V2(VersionedModel):
        SCHEMA_ID = "x.test"
        SCHEMA_VERSION = "2.0.0"

    class V3(VersionedModel):
        SCHEMA_ID = "x.test"
        SCHEMA_VERSION = "3.0.0"

    registry = SchemaRegistry()
    for model in (V1, V2, V3):
        registry.register(model)

    assert registry.supported_majors("x.test") == (3, 2)
    assert registry.is_supported("x.test", "3.0.0") is True
    assert registry.is_supported("x.test", "2.0.0") is True
    assert registry.is_supported("x.test", "1.0.0") is False  # N-2 unsupported
    assert registry.is_supported("x.test", "5.0.0") is False  # not registered


def test_parse_semver_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="invalid semantic version"):
        parse_semver("not-a-version")


def test_semver_str_round_trip() -> None:
    assert str(parse_semver("2.5.9")) == "2.5.9"


# --------------------------------------------------------------------------- JSON Schema export
def test_write_json_schemas(tmp_path: Path) -> None:
    from personalai_contracts.schemas.export import write_json_schemas

    written = write_json_schemas(tmp_path)
    assert written
    for path in written:
        assert path.exists()
        assert path.read_text(encoding="utf-8").endswith("\n")


# --------------------------------------------------------------------------- JSON Schema drift
@pytest.mark.parametrize("filename", sorted(json_schemas().keys()))
def test_committed_json_schema_matches_models(filename: str) -> None:
    committed = (JSON_DIR / filename).read_text(encoding="utf-8")
    expected = render(json_schemas()[filename])
    assert committed == expected, f"{filename} is stale - run `make schemas` and commit the result."
