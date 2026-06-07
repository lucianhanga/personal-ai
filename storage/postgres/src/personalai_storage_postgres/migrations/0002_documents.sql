-- Tracks ingested files. Chunks live in the `vectors` table with metadata.document_id linking back.
CREATE TABLE IF NOT EXISTS documents (
    id text PRIMARY KEY,
    name text NOT NULL,
    mime text NOT NULL,
    size_bytes integer NOT NULL,
    chunk_count integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
