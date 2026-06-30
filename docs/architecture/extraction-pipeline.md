# Data extraction and enrichment pipeline

## Purpose

Describe the full path a file takes from upload to searchable knowledge: text
extraction, chunking, embedding into the vector store, and named-entity extraction into
the knowledge graph (KAG). This is the ingest side of retrieval; the read side (how that
knowledge is assembled into a prompt) is documented in
[how context is built](context-assembly.md).

## Source of Truth

- Upload endpoint: `apps/backend/src/personalai_backend/app.py` (`upload_file`,
  `_make_entity_indexer`, `entity_neighborhood`).
- Text extraction + chunking: `modalities/files/src/personalai_modality_files/parser.py`
  and `.../ocr.py`.
- Embed + store: `apps/backend/src/personalai_backend/ingestion.py`.
- Entity indexing: `apps/backend/src/personalai_backend/entity_indexing.py` and
  `core/src/personalai_core/entity_extraction.py`.
- Admission gate: `apps/backend/src/personalai_backend/ollama_admission.py`.
- Folder sync/watch: `apps/backend/src/personalai_backend/folder_sync.py` and
  `.../folder_watch.py`.
- Storage adapters: `storage/postgres/src/personalai_storage_postgres/vector_repo.py`
  (pgvector) and `.../entity_store.py` (`PgEntityStore`).

## Current Behavior

### Stage diagram

```
   upload (POST /api/v1/files)
            |
            v
   [1] parse ONCE  --------------------------------> ParsedDocument(text, mime, ocr, pages)
            |   (parse_document via asyncio.to_thread)
            |       \-- PDF with no text layer + enable_ocr --> [2] OCR fallback (RapidOCR, offline)
            |
            +-------------------------+-------------------------------+
            |                         |                               |
            v                         v                               v
   [3] chunk_text            (same parsed text)              (same parsed text)
   size=1000 overlap=150              |                               |
            |                         |                               |
            v                         |                               v
   [4] embed + upsert                 |                    [5] NER -> KAG (GLOBAL scope only)
   provider.embed(chunks)             |                    entity indexer (dedicated loopback
   VectorRecord -> vectors.upsert     |                    Ollama runner, admission-gated)
   (pgvector)                         |                    extract_entities -> PgEntityStore
            |                         |                               |
            v                         v                               v
   searchable via hybrid       relational document          entities + mentions + edges
   retriever (dense + FTS)      record (bookkeeping)         (co-occurrence queryable)
```

Folder sync and folder watch (stage 6) drive the same embed + entity-indexer path for
files discovered on disk.

### Stages

**1. Ingest.** `POST /api/v1/files` -> `upload_file`. Reads at most `max_upload_bytes`
(+1 to detect oversize without buffering; 413 on overflow). The file is parsed **once**
(`parse_document` via `asyncio.to_thread`) so the extracted text feeds both embedding and
NER --- no double parse, which matters when OCR is in the path. A relational document
record is written (`storage.documents.add`).

**2. Text extraction.** `parse_document` in `parser.py`:

- `.txt` / `.md` / `.markdown`: UTF-8 decode (`errors="replace"`).
- `.pdf`: `pypdf.PdfReader`, joining each page's `extract_text()` with blank lines;
  records the page count.
- `.docx`: `python-docx`, joining paragraph text.
- Returns `ParsedDocument(text, mime, ocr, pages)`.

OCR fallback (`ocr.py`): when a PDF's text layer is empty and `enable_ocr` is set, and
the optional dependencies (`pypdfium2` + `rapidocr_onnxruntime`) are importable
(`ocr_available()`), pages are rendered at 200 DPI and run through RapidOCR (PaddleOCR
ONNX models). It is fully offline --- the recognition models ship in the wheel, nothing
leaves the host. OCR is CPU-bound (~0.6s/page), which is why parsing runs off the event
loop. If the dependencies are missing, the document degrades to the empty "no text found"
state.

**3. Chunking.** `chunk_text` (`parser.py`): overlapping character windows, `size=1000`,
`overlap=150` (step = 850).

**4. Embed and vector store.** `ingestion.py` `_chunk_embed_store` (called by
`ingest_file` and `ingest_text`): `provider.embed(chunks, embed_model)` with
`embed_model = qwen3-embedding:0.6b`, then builds one `VectorRecord` per chunk:

```python
VectorRecord(
    id=f"{document_id}:{index}",
    vector=vector,
    metadata={"document_id": ..., "name": ..., "chunk_index": index, "text": chunks[index]},
)
```

and `vectors.upsert(records, scope=scope)`. `metadata["text"]` is the lexical/FTS source
the hybrid retriever reads, and the only place a tier-2 attachment's full text is
persisted. The storage adapter is `vector_repo.py` (pgvector). Scope is `GLOBAL_SCOPE` for
the Settings -> Documents corpus, or a conversation/project `Scope` for tier-2
attachments; anti-bleed is enforced in the storage layer (RLS / scope), so a doc ingested
in one conversation never surfaces for another.

**5. NER -> KAG.** The active entity path is the indexer built by `_make_entity_indexer`
(`app.py`), called from `upload_file` after the document is stored (and from folder sync).
It runs `index_document_entities` (`entity_indexing.py`):

- Builds a **dedicated loopback `OllamaProvider`** at `ner_num_ctx` and calls
  `assert_local_provider` (fail-closed: NER must not egress).
- Admission gate `assert_ner_admission` (`ollama_admission.py`): checks the NER model fits
  within `ner_memory_fraction` (0.75) of total RAM given the current global Ollama load. If
  not, it raises `AdmissionDeferred` --- the document stays searchable (it is already
  embedded), and the KAG pass is retried on a later re-sync/reextract. Best-effort: if
  memory or Ollama state cannot be read, it admits.
- `extract_entities` (`entity_extraction.py`): LLM **structured** extraction over
  overlapping windows. Window size is model-aware --- MoE models use a small `1024`-char
  window (they return empty structured output on large windows), dense models use a `4096`-char
  window (3-4x fewer calls); `overlap=150`, capped at `30` windows. The schema is
  `ExtractedEntities{entities, relations}` with entity types `person`, `org`, `location`,
  `date`, `product`, `event`, `other`. A deterministic guard drops identifiers/codes
  (IBANs, BICs, digit-dominated strings, emails, URLs) the local model tends to
  over-extract. Per-window results are merged and de-duplicated on the canonical
  `(type, normalized-name)` key.
- Persist via `PgEntityStore` (`entity_store.py`): extraction runs **before** any purge;
  on success `purge_document_entities` clears the document's prior mentions, then
  `upsert_entity` / `add_mention` / `add_edge` write the new set. A failed extraction
  leaves prior entities untouched (data-safety: a slow cold-load must not silently wipe the
  KAG).
- KAG runs for **GLOBAL scope only**. Ephemeral conversation/project attachments (tier-2)
  are embedded and searchable but skipped for entity indexing --- their entities have no
  durable destination.

**6. Folder sync / watch.** `folder_sync.py` and `folder_watch.py` discover files on disk
and drive the same embed path and the same `_make_entity_indexer`. Folder files use a
content-addressed document id (`content_document_id`, `global-<sha256>`) so identical bytes
dedup to one vector set.

**7. Co-occurrence read.** `GET /api/v1/entities/{entity_id}/neighborhood`
(`entity_neighborhood`) returns the ego-graph for the KAG visualization: the focus entity,
the documents that mention it, and the entities that co-occur (share a document), ranked by
shared-document count (`_rank_cooccurring`).

### Per-stage summary

| Stage | Component / file | Model used | Output / store |
| --- | --- | --- | --- |
| 1 Ingest | `app.py` `upload_file` | none | bytes -> `ParsedDocument`; document record |
| 2 Extract | `parser.py` `parse_document`, `ocr.py` | none (RapidOCR for scans) | text + mime + page count |
| 3 Chunk | `parser.py` `chunk_text` | none | overlapping 1000/150 char chunks |
| 4 Embed | `ingestion.py` `_chunk_embed_store` | `qwen3-embedding:0.6b` | `VectorRecord`s -> pgvector (`vector_repo.py`) |
| 5 NER -> KAG | `entity_indexing.py`, `entity_extraction.py` | `qwen3:14b` (loopback runner) | entities + mentions + edges -> `PgEntityStore` |
| 6 Folder sync | `folder_sync.py`, `folder_watch.py` | embed + NER models | same vector + entity stores |
| 7 Co-occurrence | `app.py` `entity_neighborhood` | none | ego-graph for KAG viz |

## Ports and adapters

- `ModelProvider` (contracts) --- embeddings and the LLM NER pass go through this seam;
  the NER pass uses a dedicated loopback `OllamaProvider`.
- `VectorRepository` --- `upsert` of `VectorRecord`s; adapter `vector_repo.py` (pgvector).
- Entity-store port / `PgEntityStore` (`entity_store.py`) --- `purge_document_entities`,
  `upsert_entity`, `add_mention`, `add_edge`, and the co-occurrence reads.
- Modality parser (`parse_document`, `chunk_text`) --- pure functions over in-memory
  bytes, no network or DB.

## Constraints

- NER and embedding run on small dedicated models, not the chat model (see
  [model suite](../reference/models.md)).
- KAG indexing is GLOBAL-scope only; it is best-effort and must never fail or block an
  ingest.
- The NER runner is fail-closed local-only; the admission gate avoids out-of-memory loads.
- All input is treated as untrusted data: only text is extracted, no active content runs.

## Common Mistakes

- Assuming GLiNER does the NER. It does not --- extraction is LLM structured output. By
  default the retrieval path has no reranker (ranking is RRF); an optional cross-encoder
  reranker can be enabled with `RERANK_ENABLED` (off by default).
- Confusing `ingestion.py`'s `_maybe_extract_entities` seam (a deliberate no-op) with the
  active KAG path. The real entity indexing runs via `_make_entity_indexer` in `app.py`
  (and folder sync), not through that seam.
- Confusing `tools/markitdown-ollama/server.py` with this pipeline. That is a separate
  MarkItDown-over-Ollama tool / MCP server and is **not** part of the upload path.

## Related Decisions

- ADR-0001 (config-driven adapters; no cross-adapter imports).
- ADR-0012 (LangChain stays inside the retriever seam).

## Last Updated Notes

Verified against the code on 2026-06-30. Confirmed: parse-once, OCR via
RapidOCR/pypdfium2 at 200 DPI, chunk 1000/150, embed `qwen3-embedding:0.6b`, NER on a
dedicated loopback runner with `assert_ner_admission`, model-aware NER windows
(MoE 1024 / dense 4096, overlap 150, max 30), GLOBAL-scope-only KAG, extract-before-purge
data-safety. See also [model suite](../reference/models.md) and
[how context is built](context-assembly.md).
