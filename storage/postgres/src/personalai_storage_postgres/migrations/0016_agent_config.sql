-- #290: agent mode + per-tenant multi-agent graph configuration.
--
-- 1) agent_mode joins the per-tenant settings (tenant_settings, migration 0015) as the user-facing
--    agentic control ("single" | "multi" | "custom"); NULL inherits the deployment default.
-- 2) tenant_agent_config holds the per-tenant overrides for the multi-agent graph: each agent's
--    system prompt and the tools/MCPs disabled for it, as one JSONB document per tenant. Tenant-
--    scoped under RLS (same shape as 0009/0014/0015) so a tenant can never read or write another's
--    agent config. NO secrets here.

ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS agent_mode text;

CREATE TABLE IF NOT EXISTS tenant_agent_config (
    tenant_id  uuid PRIMARY KEY,
    config     jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_agent_config TO personalai_app;

DO $$
BEGIN
    EXECUTE 'ALTER TABLE tenant_agent_config ENABLE ROW LEVEL SECURITY';
    EXECUTE 'ALTER TABLE tenant_agent_config FORCE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS tenant_isolation ON tenant_agent_config';
    EXECUTE
        'CREATE POLICY tenant_isolation ON tenant_agent_config '
        'USING (tenant_id = current_setting(''app.tenant_id'', true)::uuid) '
        'WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true)::uuid)';
END
$$;
