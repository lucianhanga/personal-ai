-- Documents v2 P1 (#456): retain flag for the refcount/GC of folder-synced global documents.
--
-- A global document is GC-eligible only when NOTHING holds it: not a manual upload and no live
-- folder_files row. `manual_pin` is that "manual upload" holder. DEFAULT true means every EXISTING
-- global upload stays pinned (never auto-purged by the folder reconciler) -- the backfill is implicit
-- in the default. Folder-sync inserts set manual_pin = false; a doc that is BOTH manually uploaded
-- AND found in a folder stays pinned via ON CONFLICT DO UPDATE SET
--   manual_pin = documents.manual_pin OR excluded.manual_pin   (sticky-true; app-side).
--
-- Forward-only, idempotent (ADD COLUMN IF NOT EXISTS). Additive: no behavior change, retrieval and
-- the scope/anti-bleed predicate are untouched. Runs under the migration advisory lock (db.py).
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS manual_pin boolean NOT NULL DEFAULT true;

-- GC-candidate lookup: find unpinned GLOBAL docs cheaply. Partial index keeps it tiny -- it only
-- holds folder-synced (unpinned) global rows, never the pinned uploads that dominate the table.
CREATE INDEX IF NOT EXISTS idx_documents_gc_candidates
    ON documents (tenant_id)
    WHERE manual_pin = false AND conversation_id IS NULL AND project_id IS NULL;
