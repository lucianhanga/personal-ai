-- Judge fact-check flag (#465): last of the tenant_settings columns that existed in the
-- TenantSettings contract + UI but never had a column, so it silently failed to persist
-- (default_reasoning was the same bug, fixed in 0031). NULL inherits the deployment default
-- (PERSONALAI_AGENT_VERIFIER_CHECK).
ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS agent_verifier_check boolean;
