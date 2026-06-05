#!/usr/bin/env python
"""Generate the canonical JSON Schema artifacts into schemas/json/.

Usage: uv run python scripts/generate_schemas.py  (or `make schemas`).
The committed output is checked for drift in CI.
"""

from __future__ import annotations

from pathlib import Path

from personalai_contracts.schemas.export import write_json_schemas

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = REPO_ROOT / "schemas" / "json"


def main() -> None:
    written = write_json_schemas(TARGET)
    for path in sorted(written):
        print(f"wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
