"""Per-tenant multi-agent graph configuration store (#290), tenant-scoped via the RLS querier.

One JSONB document per tenant in ``tenant_agent_config`` holding each agent's prompt + disabled
tools. ``upsert`` replaces the whole document. RLS guarantees a store bound to tenant B can neither
read nor write tenant A's row -- there is no ``WHERE tenant_id`` clause; the policy enforces it.
"""

from __future__ import annotations

import json

from personalai_contracts.schemas import AgentGraphConfig
from personalai_storage_postgres.db import TENANT_ID_SQL, Querier


class PgAgentConfigStore:
    """A tenant's :class:`AgentGraphConfig`, persisted as a JSONB document under RLS."""

    def __init__(self, pool: Querier) -> None:
        self._pool = pool

    async def get(self) -> AgentGraphConfig:
        """The bound tenant's agent config, or an all-default (empty) config if none saved yet."""
        row = await self._pool.fetchrow("SELECT config FROM tenant_agent_config LIMIT 1")
        if row is None:
            return AgentGraphConfig()
        return AgentGraphConfig.from_map(json.loads(row["config"]))

    async def upsert(self, config: AgentGraphConfig) -> AgentGraphConfig:
        """Replace the bound tenant's agent config (full overwrite) and return the stored value."""
        # Store as a {agent: {prompt, disabled_tools}} map so a single agent reads back cleanly.
        doc = {
            a.name: {"prompt": a.prompt, "disabled_tools": list(a.disabled_tools)}
            for a in config.agents
        }
        row = await self._pool.fetchrow(
            f"INSERT INTO tenant_agent_config (tenant_id, config) "
            f"VALUES ({TENANT_ID_SQL}, $1::jsonb) "
            f"ON CONFLICT (tenant_id) DO UPDATE SET config = EXCLUDED.config, updated_at = now() "
            f"RETURNING config",
            json.dumps(doc),
        )
        assert row is not None
        return AgentGraphConfig.from_map(json.loads(row["config"]))
