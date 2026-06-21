-- #290 (UI redesign): per-tenant network egress settings, joining the per-tenant settings
-- (tenant_settings, migration 0015). egress_enabled gates outbound calls from in-process tools;
-- allowed_egress_hosts is the host allowlist (empty array = fail-closed, deny all). NULL on either
-- inherits the deployment default. Security-sensitive: the egress guard reads the tenant's effective
-- value per request (RLS already isolates the row; the guard falls back to boot config when unset).

ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS egress_enabled boolean;
ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS allowed_egress_hosts text[];
