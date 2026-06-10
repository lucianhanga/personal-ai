-- P0.2 (ADR-0010): tenant-scope the domain tables. tenant_id is added with a DEFAULT of the seeded
-- default tenant, so existing rows are auto-assigned (the backfill) and the column can be NOT NULL
-- immediately. P0.4 drops the DEFAULT so new inserts must set tenant_id explicitly (no silent
-- default-tenant writes). Row-Level Security policies land in P0.3.

ALTER TABLE conversations ADD COLUMN IF NOT EXISTS tenant_id uuid NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants(id);
ALTER TABLE messages ADD COLUMN IF NOT EXISTS tenant_id uuid NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants(id);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS tenant_id uuid NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants(id);
ALTER TABLE vectors ADD COLUMN IF NOT EXISTS tenant_id uuid NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants(id);
ALTER TABLE memories ADD COLUMN IF NOT EXISTS tenant_id uuid NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants(id);

-- tenant_id leads every tenant-scoped index (RLS + common queries filter on it first).
CREATE INDEX IF NOT EXISTS idx_conversations_tenant ON conversations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_messages_tenant ON messages(tenant_id);
CREATE INDEX IF NOT EXISTS idx_documents_tenant ON documents(tenant_id);
CREATE INDEX IF NOT EXISTS idx_vectors_tenant ON vectors(tenant_id);
CREATE INDEX IF NOT EXISTS idx_memories_tenant ON memories(tenant_id);
