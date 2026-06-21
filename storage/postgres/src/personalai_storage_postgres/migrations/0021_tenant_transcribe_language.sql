-- M9.2e: per-tenant spoken language for speech-to-text. "auto" detects the language (multilingual),
-- or an ISO-639-1 code (en/de/es/ro/...) pins it so Whisper does not mis-detect on real-mic audio.
-- Joins the per-tenant settings (tenant_settings, 0015). NULL inherits the deployment default
-- (PERSONALAI_TRANSCRIBE_LANGUAGE).

ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS transcribe_language text;
