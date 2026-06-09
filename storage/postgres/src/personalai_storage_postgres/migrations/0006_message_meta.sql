-- Per-message metadata (tool steps + reasoning) so the UI can show collapsible details when a
-- conversation is reopened. JSONB, nullable; older messages simply have no meta.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS meta jsonb;
