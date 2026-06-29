# 14. KAG: a relational entity store populated by local LLM-NER (first delivery of M11)

- Status: Accepted
- Date: 2026-06-29
- Relates to: ADR-0005 (PostgreSQL + pgvector storage), ADR-0001 (modular monolith / ports &
  adapters), ADR-0002 (local-first Ollama default), the M3 RAG pipeline, the §22 roadmap (M11)

## Context

The roadmap sketched **M11** as "KAG / graph memory": hybrid graph+vector retrieval on
**PostgreSQL + Apache AGE**, with entity/relationship extraction, resolution, and multi-hop
traversal, framed as a graph **upgrade of M4 long-term memory**. The goal in 0.9.0 was narrower and
more immediately useful: let the assistant reason about the **named entities across the document
corpus** (people, organizations, locations, dates, products, events) — browse them, see which
documents mention them, and answer enumeration questions like "how many invoices from X" — without
adding operational weight or breaking the local-first, fail-closed posture.

Two questions had to be settled:

1. **Graph engine.** Apache AGE (an `openCypher` extension) would add a Postgres extension to install,
   pin, and keep in sync with our migration tooling, plus a second query language in the codebase.
   The 0.9.0 graph is shallow (entity → documents, entity ↔ entity co-occurrence/edges); it does not
   need general multi-hop Cypher traversal yet.
2. **Extraction.** Named-entity extraction must run on-device (local-first) and must never degrade the
   existing RAG pipeline when it fails.

## Decision

Ship the **first delivery of M11** as a **relational entity store on the existing PostgreSQL +
pgvector spine**, populated by **local LLM named-entity extraction** wired into global document
ingest. Defer Apache AGE, general multi-hop graph retrieval, and the long-term-memory graph upgrade.

### Schema (migrations 0027–0029)

- `entities` (`0027`) — one row per resolved entity (type + canonical name), tenant-scoped (RLS).
- `entity_documents` (`0028`) — entity ↔ document mentions (the "which documents mention it" edge,
  and the unit purged when a document is deleted).
- `entity_edges` (`0029`) — entity ↔ entity relationships / co-occurrence for the graph view.

All three are RLS-isolated per tenant like the rest of the storage spine (ADR-0010).

### Extraction (local LLM-NER)

- A **dedicated small, fast local model** (`ner_model`, env `PERSONALAI_NER_MODEL`) runs NER at a
  small, **model-aware** context window — separate from the chat model so the two co-reside in memory.
- **Memory-aware admission:** before loading the NER model the app checks the **global** Ollama load
  (`/api/ps`) against `ner_memory_fraction`; if it would evict a resident model it **defers** (the
  document stays searchable; it is added to the graph on a later re-sync). It never evicts a model
  with a running task and never sends a document off-device.
- **Robustness:** a deterministic junk filter drops codes/IBANs/BICs the local model mislabels;
  extraction is windowed over the whole document; conservative **post-NER entity resolution** merges
  near-duplicate names; and a failed extraction **never wipes** the existing graph.
- Extraction is **corpus-global** and runs only for the durable corpus — documents attached to a
  single chat are not added to the graph.

### Retrieval integration

The KAG is exposed both as a browsable surface (Settings → Knowledge: graph + corpus explorer) and as
a **`RetrievalSource`** (the multi-source seam, #420): a KAG aggregation/enumeration source answers
"how many X" by resolving the query phrase to stored entities and counting/enumerating them. It is
fused with the vector sources by the graph's `merge` node (cross-source RRF + token budget).

## Consequences

- **Positive:** no new Postgres extension to operate; reuses the existing migration tooling, RLS
  model, and `RetrievalSource`/`Storage` seams; stays fully local and fail-closed; the graph is
  additive (vector RAG and semantic memory are untouched); a failed NER run degrades to "searchable
  but not graphed" rather than breaking ingest.
- **Negative / deferred:** no general multi-hop graph traversal yet (the relational edges cover the
  shallow queries we have); **Apache AGE** and the **long-term-memory graph upgrade** remain on the
  roadmap; first-time indexing of a large folder is slower because the per-document NER step is on the
  "synced" path.
- **Revisit when:** queries need true multi-hop reasoning over relationships, at which point the
  relational edges can be migrated to Apache AGE (or another graph engine) behind the same storage
  seam without touching the retrieval or ingest contracts.

## Alternatives considered

- **Apache AGE now** — rejected for 0.9.0: operational cost (extension install/pin, a second query
  language) not yet justified by the shallow queries; the storage seam keeps it a future migration.
- **A dedicated graph database (Neo4j, etc.)** — rejected: violates the single-spine, local-first
  posture and adds a service to run; out of proportion to the current need.
- **Deterministic / spaCy-style NER instead of an LLM** — rejected as the default: the local LLM
  reuses the existing Ollama runtime (no new heavy dependency or model-management surface) and handles
  multilingual corpora; a `tools/test` playground compares Ollama vs OpenAI extraction for tuning.

## Related files

- Migrations: `storage/postgres/.../migrations/0027_entities.sql`, `0028_entity_documents.sql`,
  `0029_entity_edges.sql`.
- Multi-source seam: `contracts/.../ports/retriever.py` (`RetrievalSource`, `Evidence`),
  `core/src/personalai_core/graph.py` (`gather` / `merge`, the KAG aggregation source).
- API: `GET /api/v1/entities`, `/entities/stats`, `/entities/{id}`, `/entities/{id}/neighborhood`,
  `POST /entities/reconcile`, `GET /documents/{id}/entities`, `/documents/{id}/chunks`
  (see [backend-api](../../reference/backend-api.md)).
- Guide: [Documents & folders](../../guides/documents-and-folders.md).
</content>
</invoke>
