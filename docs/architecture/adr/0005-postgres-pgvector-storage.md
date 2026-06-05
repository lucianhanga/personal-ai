# 5. PostgreSQL + pgvector as the storage/retrieval spine

- Status: Accepted
- Date: 2026-06-05

## Context

We need relational data, metadata, conversation history, and vector retrieval for RAG/memory,
ideally with minimal moving parts for a local-first install, while keeping a path to scale.

## Decision

Use **PostgreSQL** as the spine and **pgvector** for embeddings — one transactional store for
relational + metadata + vectors. Access storage through repository ports so backends are
swappable. Document **Qdrant** (Apache-2.0) as the dedicated vector-engine alternative at scale,
and (optionally) **Apache AGE** for a single-store KAG/graph layer, with **Neo4j** as the
dedicated graph alternative. **SQLite** is an acceptable desktop single-user substitution for
Postgres (open question). Data at rest is encrypted; files are jailed per workspace.

## Consequences

- Positive: fewer services, transactional consistency, simple backups, familiar SQL.
- Negative: lower raw vector throughput than dedicated engines at very large scale (acceptable
  for single-user; Qdrant path documented).

## Alternatives considered

- Dedicated vector DB from day one (Qdrant/Weaviate/Milvus) — rejected for v1 (extra service).
- NoSQL document store — rejected (lose relational integrity for this workload).
