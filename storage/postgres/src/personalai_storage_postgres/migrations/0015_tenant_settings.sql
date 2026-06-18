-- #289: per-tenant preference settings, overlaid on the boot-time CoreConfig at request time.
--
-- One row per tenant; a NULL column means "inherit the boot-time default" (the overlay only applies
-- non-null values onto CoreConfig). Tenant-scoped under RLS so a tenant can never read or write
-- another tenant's settings (same shape as 0009/0014): the app role (NOBYPASSRLS) only sees rows
-- whose tenant_id matches app.tenant_id. NO secrets live here -- AUTH_TOKEN, OPENAI_API_KEY and
-- DATABASE_URL stay env-only and are never exposed through the settings API.
--
-- tenant_id has NO default (post-0012 convention): the tenant-bound querier supplies it via the
-- coalesce(app.tenant_id, ...) expression the stores use.

CREATE TABLE IF NOT EXISTS tenant_settings (
    tenant_id            uuid PRIMARY KEY,
    model_provider       text,
    default_model        text,
    ollama_host          text,
    ollama_num_ctx       int,
    ollama_keep_alive    text,
    embed_provider       text,
    embed_model          text,
    openai_base_url      text,
    agent_graph_enabled  boolean,
    agent_human_gate     boolean,
    agent_accuracy_mode  text,
    agent_max_iterations int,
    memory_enabled       boolean,
    grounding_enabled    boolean,
    max_upload_bytes     bigint,
    updated_at           timestamptz NOT NULL DEFAULT now()
);

-- The app role (NOBYPASSRLS) the TenantQuerier assumes per transaction may use this table.
GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_settings TO personalai_app;

-- RLS: enable + force + tenant_isolation policy (same shape as migration 0009/0014).
DO $$
BEGIN
    EXECUTE 'ALTER TABLE tenant_settings ENABLE ROW LEVEL SECURITY';
    EXECUTE 'ALTER TABLE tenant_settings FORCE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS tenant_isolation ON tenant_settings';
    EXECUTE
        'CREATE POLICY tenant_isolation ON tenant_settings '
        'USING (tenant_id = current_setting(''app.tenant_id'', true)::uuid) '
        'WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true)::uuid)';
END
$$;
