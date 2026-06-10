-- Identity + tenancy foundation (ADR-0010): tenants, principals (subjects), memberships.
-- Org-ready (memberships link a subject to a tenant with a role) though the MVP uses tenant=user.
-- tenant_id columns on the domain tables + RLS land in later migrations (P0.2 / P0.3); this one is
-- purely additive.

CREATE TABLE IF NOT EXISTS tenants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS subjects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text UNIQUE,            -- nullable for service principals; stored lower-cased by the app
    display_name text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memberships (
    tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    subject_id uuid NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    role text NOT NULL DEFAULT 'member',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, subject_id)
);
CREATE INDEX IF NOT EXISTS idx_memberships_subject ON memberships(subject_id);

-- The default tenant for local / personal / dev use. Fixed id so the P0.4 backfill and the gated
-- dev-login are deterministic.
INSERT INTO tenants (id, name)
VALUES ('00000000-0000-0000-0000-000000000001', 'default')
ON CONFLICT (id) DO NOTHING;
