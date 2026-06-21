-- #298 (M9.2b): per-tenant speech-to-text settings, joining the per-tenant settings
-- (tenant_settings, migration 0015). transcribe_base_url points at an OpenAI-compatible /v1
-- transcription endpoint (a local whisper server, or OpenAI); the API key stays env-only (secret).
-- NULL inherits the deployment default (PERSONALAI_TRANSCRIBE_*).

ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS transcribe_enabled boolean;
ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS transcribe_base_url text;
ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS transcribe_model text;
