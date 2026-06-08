"""Pytest bootstrap: isolate integration tests onto a throwaway database.

Integration tests (storage/RAG/memory/conversations) talk to Postgres. To avoid polluting — and
truncating — the developer's dev database, tests run against a dedicated ``personalai_test``
database locally. CI sets ``PERSONALAI_DATABASE_URL`` to its own service container, which we honor
as-is. If Postgres is unreachable, integration tests skip as usual.
"""

from __future__ import annotations

import asyncio
import os

_ADMIN_URL = "postgresql://personalai@127.0.0.1:5432/personalai"
_TEST_URL = "postgresql://personalai@127.0.0.1:5432/personalai_test"


def _ensure_test_database() -> None:
    # Honor an explicit DSN (CI, or a developer override); only isolate the default local case.
    if os.environ.get("PERSONALAI_DATABASE_URL"):
        return

    import asyncpg

    async def _create() -> bool:
        try:
            conn = await asyncpg.connect(_ADMIN_URL)
        except Exception:
            return False  # no DB available -> integration tests will skip
        try:
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = 'personalai_test'"
            )
            if not exists:
                await conn.execute("CREATE DATABASE personalai_test")
        finally:
            await conn.close()
        return True

    if asyncio.run(_create()):
        os.environ["PERSONALAI_DATABASE_URL"] = _TEST_URL


_ensure_test_database()
