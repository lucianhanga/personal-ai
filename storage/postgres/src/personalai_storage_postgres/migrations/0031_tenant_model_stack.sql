-- Model-stack defaults (Settings -> Agents rework, A): per-task model config beyond the chat model.
-- Joins the per-tenant settings (tenant_settings, 0015). NULL on any column inherits the deployment
-- default (CoreConfig). default_reasoning was in the TenantSettings contract + UI but never had a
-- column (it silently failed to persist) -- added here alongside the new NER + reranker fields.
ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS default_reasoning text;
ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS ner_model text;
ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS rerank_enabled boolean;
ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS rerank_model text;
