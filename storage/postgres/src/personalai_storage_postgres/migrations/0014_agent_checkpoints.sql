-- M8.1a (ADR-0012): durable LangGraph checkpoints, tenant-scoped under RLS.
--
-- LangGraph's checkpoint IS the durable interrupt/resume state (it replaces the hand-rolled
-- pending_runs table from the M8 primitives design). It is stored tenant-scoped so RLS makes a
-- cross-tenant resume impossible at the DB layer (matches 0009): the TenantCheckpointSaver is bound
-- to one tenant and writes through TenantDb (SET LOCAL ROLE personalai_app + app.tenant_id), so a
-- saver bound to tenant B cannot see tenant A's threads. tenant_id has NO default (post-0012
-- convention): the tenant-bound saver always supplies it explicitly.

CREATE TABLE IF NOT EXISTS agent_checkpoints (
    tenant_id            uuid NOT NULL,
    thread_id            text NOT NULL,
    checkpoint_ns        text NOT NULL DEFAULT '',
    checkpoint_id        text NOT NULL,
    parent_checkpoint_id text,
    type                 text,                       -- serializer type tag for `checkpoint`
    checkpoint           bytea NOT NULL,             -- serde.dumps_typed(checkpoint)
    metadata_type        text,                       -- serializer type tag for `metadata`
    metadata             bytea NOT NULL,             -- serde.dumps_typed(metadata)
    created_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, thread_id, checkpoint_ns, checkpoint_id)
);

CREATE TABLE IF NOT EXISTS agent_checkpoint_writes (
    tenant_id     uuid NOT NULL,
    thread_id     text NOT NULL,
    checkpoint_ns text NOT NULL DEFAULT '',
    checkpoint_id text NOT NULL,
    task_id       text NOT NULL,
    idx           int  NOT NULL,
    channel       text NOT NULL,
    type          text,                              -- serializer type tag for `blob`
    blob          bytea NOT NULL,                    -- serde.dumps_typed(value)
    PRIMARY KEY (tenant_id, thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);

-- The app role (NOBYPASSRLS) the TenantDb assumes per transaction may use these tables.
GRANT SELECT, INSERT, UPDATE, DELETE ON agent_checkpoints, agent_checkpoint_writes TO personalai_app;

-- RLS: enable + force + tenant_isolation policy on both tables (same shape as migration 0009).
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['agent_checkpoints', 'agent_checkpoint_writes']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I '
            'USING (tenant_id = current_setting(''app.tenant_id'', true)::uuid) '
            'WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true)::uuid)',
            t
        );
    END LOOP;
END
$$;
