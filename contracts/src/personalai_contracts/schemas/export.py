"""Export the canonical JSON Schema for every versioned contract.

JSON Schema is the canonical interchange format (ADR-0003). These artifacts are committed under
``schemas/json/`` at the repo root and are the source the TS/Zod bindings are aligned against.
A test (and the ``make schemas`` target) keeps the committed files in sync with the models.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from personalai_contracts.schemas.registry import _builtin_models


def _filename(schema_id: str, version: str) -> str:
    return f"{schema_id}-{version}.json"


def json_schemas() -> dict[str, dict[str, Any]]:
    """Return ``{filename: json_schema_dict}`` for every built-in contract."""
    out: dict[str, dict[str, Any]] = {}
    for model in _builtin_models():
        schema = model.model_json_schema(by_alias=True)
        out[_filename(model.SCHEMA_ID, model.SCHEMA_VERSION)] = schema
    return out


def render(schema: dict[str, Any]) -> str:
    """Deterministic JSON rendering (stable diffs)."""
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def write_json_schemas(target_dir: Path) -> list[Path]:
    """Write all JSON Schemas into ``target_dir``; return the paths written."""
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for filename, schema in json_schemas().items():
        path = target_dir / filename
        path.write_text(render(schema), encoding="utf-8")
        written.append(path)
    return written
