-- Documents v2 P3 (#451): canonical named entities for KAG. ADDITIVE -- no change to vectors/documents,
-- so retrieval and the scope/anti-bleed predicate are untouched. Entities derive ONLY from the durable
-- GLOBAL corpus (NER is scope.is_global-gated in ingestion.py::_maybe_extract_entities), so the entity
-- tables carry NO scope columns; tenant is the only isolation dimension (RLS).
--
-- One row per (type, normalized_name) per tenant. normalized_name is GENERATED (lower + trim + collapse
-- whitespace), so the canonical key cannot be bypassed by a caller; UNIQUE(tenant_id, type,
-- normalized_name) is the dedup/upsert target that folds re-extractions of the same entity across many
-- documents into a single row. Semantic alias/synonym/coref folding ("IBM" == "International Business
-- Machines") is the EXTRACTOR's job, not the DB's -- the DB only does lexical canonicalization.
--
-- Forward-only, idempotent. uuid PK => no sequences, no sequence grants. pg_trgm is created the same
-- owner-connection way `vector` is in 0001 (migrations run as the table owner / superuser).
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS entities (
    id              uuid        NOT NULL DEFAULT gen_random_uuid(),
    tenant_id       uuid        NOT NULL REFERENCES tenants(id),
    type            text        NOT NULL
                      CHECK (type IN ('person','org','location','date','product','event','other')),
    name            text        NOT NULL,                    -- display form (last writer wins on upsert)
    normalized_name text        NOT NULL GENERATED ALWAYS AS
                      (lower(regexp_replace(trim(name), '\s+', ' ', 'g'))) STORED,
    mention_count   integer     NOT NULL DEFAULT 0,          -- denormalized sum of entity_documents.occurrences
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),                             -- also the unique target for the child FKs
    UNIQUE (tenant_id, type, normalized_name)               -- dedup / canonical upsert key
);

-- (a) listing by type + (b) the canonical upsert lookup are BOTH served by the UNIQUE constraint's
--     index (tenant_id, type, normalized_name). (c) fuzzy/substring name search:
CREATE INDEX IF NOT EXISTS idx_entities_name_trgm
    ON entities USING gin (normalized_name gin_trgm_ops);
-- "most prominent entities" dashboards / KAG ranking:
CREATE INDEX IF NOT EXISTS idx_entities_prominence
    ON entities (tenant_id, mention_count DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON entities TO personalai_app;
ALTER TABLE entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE entities FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON entities;
CREATE POLICY tenant_isolation ON entities
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
