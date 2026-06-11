-- B2 (audit M1): tenant-scope the uniqueness of vectors/documents. A global single-column id PK lets
-- one tenant's id collide with another's, which under RLS turns INSERT ... ON CONFLICT into a hard
-- error against an invisible row -- a cross-tenant DoS / existence oracle. Composite (tenant_id, id)
-- removes the shared keyspace entirely. No FK references these ids, so the PK swap is safe.
ALTER TABLE vectors DROP CONSTRAINT IF EXISTS vectors_pkey;
ALTER TABLE vectors ADD PRIMARY KEY (tenant_id, id);

ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_pkey;
ALTER TABLE documents ADD PRIMARY KEY (tenant_id, id);
