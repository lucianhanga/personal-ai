-- Vector store for RAG (pgvector). Dimension matches mxbai-embed-large (1024); changing the
-- embedding model requires a new migration. Metadata carries the chunk text + source/locator.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS vectors (
    id text PRIMARY KEY,
    embedding vector(1024) NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS vectors_embedding_hnsw
    ON vectors USING hnsw (embedding vector_cosine_ops);
