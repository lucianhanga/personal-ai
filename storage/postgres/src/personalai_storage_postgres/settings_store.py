"""Per-tenant preference settings store (#289), tenant-scoped via the RLS-bound querier.

One row per tenant in ``tenant_settings``; a NULL column means "inherit the boot-time default".
``upsert`` replaces the whole row (the settings form sends every field), so clearing a field back to
NULL restores the default. RLS guarantees a store bound to tenant B can neither read nor write
tenant A's row -- there is no ``WHERE tenant_id`` clause because the policy enforces it at the DB.
"""

from __future__ import annotations

import asyncpg

from personalai_contracts.schemas import TenantSettings
from personalai_storage_postgres.db import TENANT_ID_SQL, Querier

# Column order shared by SELECT / INSERT / RETURNING; matches TenantSettings field order.
_FIELDS = (
    "model_provider",
    "default_model",
    "ollama_host",
    "ollama_num_ctx",
    "ollama_keep_alive",
    "embed_provider",
    "embed_model",
    "openai_base_url",
    "agent_mode",
    "agent_graph_enabled",
    "agent_human_gate",
    "agent_accuracy_mode",
    "agent_max_iterations",
    "agent_timeout_seconds",
    "memory_enabled",
    "grounding_enabled",
    "max_upload_bytes",
    "egress_enabled",
    "allowed_egress_hosts",
    "transcribe_enabled",
    "transcribe_provider",
    "transcribe_base_url",
    "transcribe_model",
)
_COLS = ", ".join(_FIELDS)


class PgSettingsStore:
    """A tenant's :class:`TenantSettings`, persisted in Postgres under RLS."""

    def __init__(self, pool: Querier) -> None:
        self._pool = pool

    async def get(self) -> TenantSettings:
        """The bound tenant's settings, or an all-inherit (all-None) default if none saved yet."""
        row = await self._pool.fetchrow(f"SELECT {_COLS} FROM tenant_settings LIMIT 1")
        return _to_settings(row) if row is not None else TenantSettings()

    async def upsert(self, settings: TenantSettings) -> TenantSettings:
        """Replace the bound tenant's settings row (full overwrite) and return the stored value."""
        # asyncpg encodes a Python list (not tuple) to a Postgres array (allowed_egress_hosts).
        values = [_array_safe(getattr(settings, f)) for f in _FIELDS]
        # $1..$N are the field values; tenant_id comes from the RLS GUC (coalesce expression).
        placeholders = ", ".join(f"${i}" for i in range(1, len(_FIELDS) + 1))
        assignments = ", ".join(f"{f} = EXCLUDED.{f}" for f in _FIELDS)
        row = await self._pool.fetchrow(
            f"INSERT INTO tenant_settings (tenant_id, {_COLS}) "
            f"VALUES ({TENANT_ID_SQL}, {placeholders}) "
            f"ON CONFLICT (tenant_id) DO UPDATE SET {assignments}, updated_at = now() "
            f"RETURNING {_COLS}",
            *values,
        )
        assert row is not None
        return _to_settings(row)


def _array_safe(value: object) -> object:
    """Tuples -> lists so asyncpg encodes them as Postgres arrays; everything else unchanged."""
    return list(value) if isinstance(value, tuple) else value


def _to_settings(row: asyncpg.Record) -> TenantSettings:
    # text[] columns come back as Python lists; pydantic coerces them to the tuple fields.
    return TenantSettings(**{f: row[f] for f in _FIELDS})
