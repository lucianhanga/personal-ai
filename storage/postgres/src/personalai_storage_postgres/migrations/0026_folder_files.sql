-- Documents v2 P1 (#456): per-file sync state for every file under a watched folder.
--
-- SOFT LINK to documents (document_id text, NO foreign key) -- deliberately mirroring the existing
-- vectors<->documents relationship (a vector's id is "{document_id}:{index}" and metadata.document_id
-- points back; there is no FK, and delete_file() in app.py deletes vectors EXPLICITLY via chunk_ids()).
-- The reconciler owns document/vector deletion, so a soft link is required, not just preferred:
--   * document_id is NULL while a file is pending/indexing (the doc does not exist yet);
--   * when a document is purged, the file must be DEMOTED to 'stale'/'pending' for re-index, which an
--     ON DELETE FK action cannot express (CASCADE would wrongly delete the still-on-disk file's row,
--     SET NULL cannot also flip status).
-- Dedup across folders is automatic: identical bytes => identical content-addressed documents.id, so
-- two folder_files rows resolve to ONE document (the embed step is idempotent on that id).
--
-- Natural PK (tenant_id, folder_source_id, rel_path) = the scan-lookup key AND the upsert conflict
-- target. Composite FK to folder_sources ON DELETE CASCADE: removing a folder source purges all its
-- file rows in one statement; the now-unreferenced documents fall out of the refcount and are swept
-- by the reconciler (0024's manual_pin gate keeps manual uploads safe).
--
-- Forward-only, idempotent. fillfactor 85 leaves HOT-update headroom for the high-churn status /
-- last_seen_scan / updated_at columns (kept OUT of unique indexes so updates stay HOT, less bloat).
CREATE TABLE IF NOT EXISTS folder_files (
    tenant_id        uuid        NOT NULL REFERENCES tenants(id),
    folder_source_id uuid        NOT NULL,
    rel_path         text        NOT NULL,                      -- path relative to root_path
    -- fingerprint: size+mtime_ns is the cheap fast-path the SCANNER sets; content_sha256 is the
    -- authoritative hash the embed WORKER computes/overwrites at (re)index time.
    size_bytes       bigint      NOT NULL,
    mtime_ns         bigint      NOT NULL,                      -- os.stat().st_mtime_ns (nanoseconds)
    content_sha256   text,                                      -- NULL until the worker hashes it
    -- soft link to the content-addressed GLOBAL document (= documents.id when synced)
    document_id      text,
    -- status: green=synced; amber=pending/indexing/stale; red=error; grey=deleted (tombstone)
    status           text        NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending','indexing','synced','stale','error','deleted')),
    error_code       text,                                      -- machine-readable failure class
    error_detail     text,                                      -- human-readable detail
    last_seen_scan   bigint      NOT NULL DEFAULT 0,            -- = folder_sources.scan_generation last seen
    indexed_at       timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, folder_source_id, rel_path),
    FOREIGN KEY (tenant_id, folder_source_id)
        REFERENCES folder_sources (tenant_id, id) ON DELETE CASCADE
) WITH (fillfactor = 85);

-- (a) status-filtered pagination per folder (keyset on rel_path for stable ordering).
CREATE INDEX IF NOT EXISTS idx_folder_files_status_page
    ON folder_files (tenant_id, folder_source_id, status, rel_path);

-- (b) document_id refcount lookups (the GC "is this doc still held?" probe). Partial = only synced rows.
CREATE INDEX IF NOT EXISTS idx_folder_files_document
    ON folder_files (tenant_id, document_id) WHERE document_id IS NOT NULL;

-- (c) mark-and-sweep tombstoning: WHERE folder_source_id=? AND last_seen_scan < :gen AND status<>'deleted'.
CREATE INDEX IF NOT EXISTS idx_folder_files_sweep
    ON folder_files (tenant_id, folder_source_id, last_seen_scan);

-- (d) embed worker pull (tiny partial over just the work backlog).
CREATE INDEX IF NOT EXISTS idx_folder_files_workqueue
    ON folder_files (tenant_id, updated_at) WHERE status IN ('pending','stale');

-- (e) dedup / locate-all-copies of a content hash (same file across folders).
CREATE INDEX IF NOT EXISTS idx_folder_files_sha
    ON folder_files (tenant_id, content_sha256) WHERE content_sha256 IS NOT NULL;

-- High-churn table: tighten autovacuum so dead tuples from per-scan updates are reclaimed promptly.
ALTER TABLE folder_files SET (autovacuum_vacuum_scale_factor = 0.02);

-- RLS + grant (0009 does not cover this table).
GRANT SELECT, INSERT, UPDATE, DELETE ON folder_files TO personalai_app;
ALTER TABLE folder_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE folder_files FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON folder_files;
CREATE POLICY tenant_isolation ON folder_files
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
