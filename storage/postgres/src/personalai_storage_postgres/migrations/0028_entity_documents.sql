-- Documents v2 P3 (#451): the entity<->document mention link (M:N).
--
-- document_id is a SOFT link to documents.id (NO foreign key), mirroring vectors<->documents and
-- folder_files<->documents: the reconciler deletes mentions when a document is purged (same place
-- vectors are deleted via chunk_ids). entity_id IS a hard composite FK to entities ON DELETE CASCADE --
-- it is the same subsystem, so removing an entity auto-removes its mentions.
--
-- Forward-only, idempotent. uuid PK on parent => no sequences here either.
CREATE TABLE IF NOT EXISTS entity_documents (
    tenant_id   uuid        NOT NULL REFERENCES tenants(id),
    entity_id   uuid        NOT NULL,
    document_id text        NOT NULL,                        -- soft link to documents.id (reconciler-managed)
    occurrences integer     NOT NULL DEFAULT 1,              -- mentions of this entity in this document
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, entity_id, document_id),
    FOREIGN KEY (tenant_id, entity_id)
        REFERENCES entities (tenant_id, id) ON DELETE CASCADE
);

-- (a) "entities of a document" + the doc-purge DELETE WHERE document_id = ? (leading document_id):
CREATE INDEX IF NOT EXISTS idx_entity_documents_by_doc
    ON entity_documents (tenant_id, document_id);
-- (b) "documents of an entity" (refcount / orphan check) is served by the PK's (tenant_id, entity_id)
--     left-prefix -- no extra index needed.

GRANT SELECT, INSERT, UPDATE, DELETE ON entity_documents TO personalai_app;
ALTER TABLE entity_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE entity_documents FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON entity_documents;
CREATE POLICY tenant_isolation ON entity_documents
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
