-- Long-term semantic memory (M4-2). Embedding dim matches mxbai-embed-large (1024).
-- `source` carries provenance (conversation_id / message id / document id).
CREATE TABLE IF NOT EXISTS memories (
    id text PRIMARY KEY,
    kind text NOT NULL,
    text text NOT NULL,
    embedding vector(1024) NOT NULL,
    confidence real NOT NULL DEFAULT 0.7,
    source jsonb NOT NULL DEFAULT '{}'::jsonb,
    superseded boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS memories_embedding_hnsw
    ON memories USING hnsw (embedding vector_cosine_ops);
