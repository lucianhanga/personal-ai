-- M9.3: per-tenant text-to-speech (read answers aloud) toggle. Slice 1 reads aloud via the
-- browser's speech synthesis; this flag gates the read-aloud control. Joins the per-tenant settings
-- (tenant_settings, 0015). NULL inherits the deployment default (PERSONALAI_TTS_ENABLED).

ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS tts_enabled boolean;
