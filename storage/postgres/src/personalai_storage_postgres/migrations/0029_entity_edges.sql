-- Documents v2 P3 (#451): the entity<->entity graph for KAG traversal.
--
-- Both endpoints are hard composite FKs to entities ON DELETE CASCADE, so deleting an entity removes
-- every edge it participates in (src OR dst) -- the orphan sweep in 0027/0028 needs no separate edge
-- cleanup. weight/occurrences is an aggregate evidence counter. CHECK src <> dst forbids self-loops.
--
-- weight is an AGGREGATE with no per-document provenance, so a single document's purge cannot precisely
-- decrement the edges it contributed -- edges are removed only when an endpoint entity disappears
-- (cascade). For P3 edge weights are advisory / rebuildable from a re-aggregation pass; exact per-doc
-- edge refcounting would need an additive entity_edge_documents provenance table (a clean future 0030).
--
-- Forward-only, idempotent.
CREATE TABLE IF NOT EXISTS entity_edges (
    tenant_id     uuid        NOT NULL REFERENCES tenants(id),
    src_entity_id uuid        NOT NULL,
    relation      text        NOT NULL,                      -- extractor-provided predicate
    dst_entity_id uuid        NOT NULL,
    weight        integer     NOT NULL DEFAULT 1,            -- aggregate co-occurrence / evidence count
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, src_entity_id, relation, dst_entity_id),
    CHECK (src_entity_id <> dst_entity_id),
    FOREIGN KEY (tenant_id, src_entity_id)
        REFERENCES entities (tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, dst_entity_id)
        REFERENCES entities (tenant_id, id) ON DELETE CASCADE
);

-- Outgoing traversal from a node is served by the PK's (tenant_id, src_entity_id) left-prefix.
-- Reverse (incoming) traversal -- "what points at this node":
CREATE INDEX IF NOT EXISTS idx_entity_edges_reverse
    ON entity_edges (tenant_id, dst_entity_id, relation);

GRANT SELECT, INSERT, UPDATE, DELETE ON entity_edges TO personalai_app;
ALTER TABLE entity_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE entity_edges FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON entity_edges;
CREATE POLICY tenant_isolation ON entity_edges
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
