-- Documents v2 P1 (#456): registered folder roots for continuous sync (Settings -> Documents,
-- GLOBAL corpus).
--
-- Tenant-scoped under RLS (same pattern as 0009). UNIQUE (tenant_id, id) lets folder_files carry a
-- tenant-consistent COMPOSITE FK (tenant_id, folder_source_id) -> here, the same trick 0023 used to
-- make conversations FK-able. scan_generation is the mark-and-sweep watermark: bumped at scan start,
-- stamped onto every file seen; survivors keep the new generation, vanished files keep an older one.
--
-- Forward-only, idempotent. No sequences (uuid PK), so no sequence grants needed.
CREATE TABLE IF NOT EXISTS folder_sources (
    id                    uuid        NOT NULL DEFAULT gen_random_uuid(),
    tenant_id             uuid        NOT NULL REFERENCES tenants(id),
    root_path             text        NOT NULL,                 -- absolute watched root
    label                 text        NOT NULL,
    enabled               boolean     NOT NULL DEFAULT true,
    recursive             boolean     NOT NULL DEFAULT true,
    include_globs         text[]      NOT NULL DEFAULT '{}',
    exclude_globs         text[]      NOT NULL DEFAULT '{}',
    max_file_bytes        bigint,                               -- NULL = no per-file cap
    follow_symlinks       boolean     NOT NULL DEFAULT false,
    -- status: green=idle (healthy/synced), amber=scanning, red=error, grey=disabled
    status                text        NOT NULL DEFAULT 'idle'
                            CHECK (status IN ('idle','scanning','error','disabled')),
    status_detail         text,
    scan_generation       bigint      NOT NULL DEFAULT 0,       -- mark/sweep watermark
    last_scan_started_at  timestamptz,
    last_scan_finished_at timestamptz,                          -- the "last-scan watermark" the UI shows
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, id),                                     -- target for folder_files' composite FK
    UNIQUE (tenant_id, root_path)                              -- one registration per root per tenant
);

CREATE INDEX IF NOT EXISTS idx_folder_sources_tenant ON folder_sources (tenant_id);

-- RLS (ADR-0010): the app drops to NOBYPASSRLS personalai_app + sets app.tenant_id per txn. 0009's
-- GRANT list does NOT include new tables, so grant + enable here explicitly. current_setting(...,true)
-- returns NULL when unset => fail-closed.
GRANT SELECT, INSERT, UPDATE, DELETE ON folder_sources TO personalai_app;
ALTER TABLE folder_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE folder_sources FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON folder_sources;
CREATE POLICY tenant_isolation ON folder_sources
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
