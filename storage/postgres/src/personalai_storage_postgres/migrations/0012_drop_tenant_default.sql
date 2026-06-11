-- P0.4 (ADR-0010): drop the tenant_id column DEFAULT now that every INSERT sets tenant_id explicitly
-- (stores use coalesce(current_setting('app.tenant_id', true), default)). This removes the silent
-- default-tenant fallback at the schema level, so a write that somehow omits tenant_id fails loudly
-- (NOT NULL) instead of landing in the default tenant. Existing rows already carry tenant_id.
ALTER TABLE conversations ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE messages ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE documents ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE vectors ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE memories ALTER COLUMN tenant_id DROP DEFAULT;
