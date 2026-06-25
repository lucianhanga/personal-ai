-- Phase 0 PR1 (#420 / #423): the shared, scope-parameterized RAG storage foundation.
--
-- Purely ADDITIVE, ZERO behavior change. Adds a generic scope dimension to `vectors` and `documents`
-- so one shared corpus serves global / conversation / project scopes, plus a lexical (FTS) arm for a
-- future dense+lexical hybrid retriever. Existing rows get conversation_id/project_id = NULL/NULL,
-- which is exactly today's global corpus -- no data migration, and the application keeps reading and
-- writing the global scope until the scope predicate is threaded through (this same PR's plumbing).
--
-- Forward-only (the repo has no down-migrations) and idempotent (IF NOT EXISTS / guarded DO-blocks),
-- matching the existing migration style. The whole file runs inside one transaction under the
-- migration advisory lock (db.py::apply_migrations).

-- (a) conversations needs a UNIQUE (tenant_id, id) so the scope FKs below can be composite and
--     tenant-consistent. Its PK is still single-column `id` (0003) -- 0013 only made vectors/documents
--     composite. `id` is already unique, so (tenant_id, id) is trivially unique on existing rows; this
--     ADD CONSTRAINT validates instantly. A composite FK forces a row's scope parent into the SAME
--     tenant (a vector cannot point at another tenant's conversation) and keeps the cascade
--     tenant-consistent.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM pg_constraint WHERE conname = 'conversations_tenant_id_key'
    ) THEN
        ALTER TABLE conversations ADD CONSTRAINT conversations_tenant_id_key UNIQUE (tenant_id, id);
    END IF;
END
$$;

-- NOTE on `projects`: the Projects epic (#409) has NOT created a projects table yet. We therefore add
-- the `project_id` COLUMN now (so the scope shape is final and forward-compatible) but DEFER its
-- foreign key to #409. The composite FK
--     FOREIGN KEY (tenant_id, project_id) REFERENCES projects(tenant_id, id) ON DELETE CASCADE
-- lands in the Projects migration. Do not invent a projects table here.

-- (b) Scope columns + constraints on `vectors` (the retrieval-critical table).
ALTER TABLE vectors
    ADD COLUMN IF NOT EXISTS conversation_id text,
    ADD COLUMN IF NOT EXISTS project_id      text;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM pg_constraint WHERE conname = 'vectors_scope_exclusive'
    ) THEN
        -- A row is at most one scope. NULL/NULL = global; one set = conversation- or project-scoped.
        ALTER TABLE vectors ADD CONSTRAINT vectors_scope_exclusive
            CHECK (conversation_id IS NULL OR project_id IS NULL);
    END IF;
    IF NOT EXISTS (
        SELECT FROM pg_constraint WHERE conname = 'vectors_conversation_fk'
    ) THEN
        -- Conversation-scoped vectors die with their conversation (no app code, no orphans).
        ALTER TABLE vectors ADD CONSTRAINT vectors_conversation_fk
            FOREIGN KEY (tenant_id, conversation_id)
            REFERENCES conversations (tenant_id, id) ON DELETE CASCADE;
    END IF;
    -- vectors_project_fk: DEFERRED to #409 (projects table does not exist yet).
END
$$;

-- (c) Same scope columns + constraints on `documents`.
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS conversation_id text,
    ADD COLUMN IF NOT EXISTS project_id      text;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM pg_constraint WHERE conname = 'documents_scope_exclusive'
    ) THEN
        ALTER TABLE documents ADD CONSTRAINT documents_scope_exclusive
            CHECK (conversation_id IS NULL OR project_id IS NULL);
    END IF;
    IF NOT EXISTS (
        SELECT FROM pg_constraint WHERE conname = 'documents_conversation_fk'
    ) THEN
        ALTER TABLE documents ADD CONSTRAINT documents_conversation_fk
            FOREIGN KEY (tenant_id, conversation_id)
            REFERENCES conversations (tenant_id, id) ON DELETE CASCADE;
    END IF;
    -- documents_project_fk: DEFERRED to #409 (projects table does not exist yet).
END
$$;

-- (d) Lexical arm for the future dense+lexical RRF hybrid retriever. STORED generated tsvector over
--     the chunk text that ingestion writes to metadata->>'text' (confirmed in ingestion.py::ingest_file).
--     The `simple` config lowercases + unicode-normalizes with NO language-specific stemming -- neutral
--     and strictly better than `english` for a multilingual personal corpus (it does not zero out
--     non-English terms). One GIN index serves all scopes; the scope predicate filters lexically too.
ALTER TABLE vectors
    ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('simple', coalesce(metadata->>'text', ''))) STORED;
CREATE INDEX IF NOT EXISTS idx_vectors_tsv ON vectors USING gin (tsv);

-- (e) Scoped-retrieval + GC-sweep indexes. Partial (WHERE NOT NULL) keeps the global hot path's index
--     tiny and lets scoped lookups + conversation-delete cascades avoid full scans. tenant_id leads
--     (RLS filters it first). The 1024-dim HNSW from 0001 is unchanged -- one ANN index serves every
--     scope; the scope predicate is an additional WHERE, and _init_connection's
--     `hnsw.iterative_scan = relaxed_order` keeps a scoped (filtered) ANN returning a full k.
CREATE INDEX IF NOT EXISTS idx_vectors_scope_conv
    ON vectors (tenant_id, conversation_id) WHERE conversation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_vectors_scope_proj
    ON vectors (tenant_id, project_id) WHERE project_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_documents_scope_conv
    ON documents (tenant_id, conversation_id) WHERE conversation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_documents_scope_proj
    ON documents (tenant_id, project_id) WHERE project_id IS NOT NULL;
