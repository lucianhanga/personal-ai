-- #290: per-tenant whole-turn timeout (seconds). Joins the per-tenant settings (tenant_settings,
-- migration 0015); NULL inherits the deployment default (PERSONALAI_AGENT_TIMEOUT_SECONDS). Lets a
-- tenant raise the wall-clock cap when running a slow model + the multi-agent reflection loop.

ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS agent_timeout_seconds int;
