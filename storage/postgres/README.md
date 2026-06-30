# storage/postgres (`personalai_storage_postgres`)

Storage adapters for **PostgreSQL + pgvector** (ADR-0005), via **asyncpg**. Depends inward on
`personalai_contracts` only (ADR-0001).

- `create_pool(database_url)` / `apply_migrations(pool)` — pool + forward-only SQL migrations.
- `PgVectorRepository` — implements the `VectorRepository` port (upsert / cosine-similarity
  query / delete) over a `vectors` table. Embedding dim 1024 (qwen3-embedding:0.6b).

Run a local DB with `make db` (docker-compose `pgvector/pgvector`). Relational repos for documents
and conversations build on the same pool.
