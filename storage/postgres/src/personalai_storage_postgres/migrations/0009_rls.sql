-- P0.3 (ADR-0010): Row-Level Security tenant isolation on the domain tables.
--
-- The app drops to a NOBYPASSRLS role per transaction (SET LOCAL ROLE personalai_app, see TenantDb)
-- and sets app.tenant_id; the policies then restrict every row to that tenant. FORCE makes the
-- table owner subject to RLS too. Migrations/system jobs run as the (superuser/owner) connection,
-- which bypasses RLS. current_setting(..., true) returns NULL when unset => no rows match =>
-- fail-closed (a query without a bound tenant sees nothing and cannot insert).

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'personalai_app') THEN
        CREATE ROLE personalai_app NOLOGIN NOBYPASSRLS;
    END IF;
END
$$;

-- Let the connecting (app) user assume the app role per transaction.
GRANT personalai_app TO CURRENT_USER;
GRANT SELECT, INSERT, UPDATE, DELETE ON conversations, messages, documents, vectors, memories
    TO personalai_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO personalai_app;

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['conversations', 'messages', 'documents', 'vectors', 'memories']
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
