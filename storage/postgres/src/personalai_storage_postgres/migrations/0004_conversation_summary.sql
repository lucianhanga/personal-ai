-- Short-term memory (M4-1): a rolling summary of older turns + how many leading messages it covers.
-- `incognito` (plumbed here) will disable long-term memory writes (M4-2/3).
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS summary text;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS summary_through integer NOT NULL DEFAULT 0;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS incognito boolean NOT NULL DEFAULT false;
