-- P1.3 (ADR-0010): server-side, revocable sessions. Looked up by the opaque token's hash before a
-- tenant context exists (the session establishes the tenant), so this identity-layer table is NOT
-- RLS-gated; the token hash is the credential. Idle + absolute expiry windows.
CREATE TABLE IF NOT EXISTS sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id uuid NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,            -- sha256 of the opaque token; never the token itself
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    idle_expires_at timestamptz NOT NULL,       -- slides on each use
    absolute_expires_at timestamptz NOT NULL    -- hard cap
);
CREATE INDEX IF NOT EXISTS idx_sessions_subject ON sessions(subject_id);
