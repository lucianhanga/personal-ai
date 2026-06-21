-- #300 (M9.2c): per-tenant transcription provider choice ("local" in-process faster-whisper, or
-- "openai_compat" whisper server). Joins the per-tenant settings (tenant_settings, 0015). NULL
-- inherits the deployment default (PERSONALAI_TRANSCRIBE_PROVIDER).

ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS transcribe_provider text;
