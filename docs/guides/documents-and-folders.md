# Documents & folders: keep your files searchable (Documents v2)

PersonalAI can answer over your own documents two ways, both fully on-device. Settings → **Documents**
has two regions:

1. **Individual uploads** — drop a file in; it is parsed, embedded, and added to the global corpus.
2. **Folder sources** — grant a local folder; the app **continuously keeps it in sync** with the
   index as files are added, changed, or deleted, and builds a **knowledge graph** of the entities it
   finds.

Everything here runs locally: parsing, OCR, embeddings, and entity extraction all use your local
models. The folder sync is **fail-closed to local providers** — a background sync never reaches the
network, even if you have remote providers configured.

## 1. Prerequisites

- The backend must have a database (Postgres + pgvector) — folder sync and the entity graph are
  persisted there. In local mode this is the bundled dev database (`make db`).
- A local embedding model (default `qwen3-embedding:0.6b`) for the vector index, and a local chat
  model for named-entity extraction. See [files-and-rag](./files-and-rag.md) for RAG setup.

## 2. Supported files

`txt`, `markdown`, `pdf`, and `docx`. A **scanned / image-only PDF** (no text layer) is **OCR'd
on-device** — pages are rendered and read with RapidOCR — so it becomes searchable like any other
document. A PDF that genuinely has no recoverable text reports "no text found" rather than failing.

## 3. Individual uploads

Drop a file onto the uploads region (or pick one). It is parsed (with OCR if needed), chunked,
embedded, and listed. Small documents attached **in chat** are folded into the message; larger ones
are indexed into the conversation and retrieved with citations. Removing an upload deletes its
vectors.

## 4. Folder sources

### Adding a folder

A browser cannot read an arbitrary local path, but the **backend runs on your machine and can**. So
you grant a folder by typing/pasting its **absolute path**; the backend validates it (exists, is a
directory, readable, inside an allowed root, no symlink escape) before registering it. (A browser
folder picker is deliberately not used — it yields a per-session handle, not a stable path a
background watcher can follow.)

Give it a label and add it. The initial scan + index starts immediately in the background.

### What you see

Each folder is a **card** with a status pill and a live rollup of its files, updated over a live
stream:

- **green — synced / idle:** the folder is fully indexed and healthy.
- **amber — scanning / indexing:** a scan or (re)index is in progress.
- **red — error:** the folder is unreachable or some files failed (the card shows how many).

The rollup reads like `312 synced · 4 indexing · 1 error`. Expand a card to drill into a
**collapsible directory tree** that mirrors the folder's structure: each subdirectory shows a rollup
of its descendants' statuses, and each file row shows its status, size, indexed time, and — on
failure — the error. A status filter, name search, and "Load more" keep large folders manageable.

### Controls

- **Pause / Resume** — stop or restart watching + syncing a folder.
- **Re-sync** — force a full reconciliation (also runs automatically on startup and periodically).
- **Remove** — a confirm dialog states exactly what will be purged (the folder's indexed chunks and
  its extracted entities); only confirming deletes them.

### How sync works

The database is the source of truth — a crash or a missed filesystem event is always recovered by a
re-scan. A native filesystem watcher catches live edits, a periodic safety-net scan catches anything
the watcher dropped, and a full reconcile runs at startup. Identical files (same content) across two
folders share **one** index entry; deleting a file removes its index entry only once nothing else
references it. Individually uploaded documents are never auto-purged by folder sync.

> **Heads-up on speed.** A file is marked **synced** only after its *whole* pipeline finishes —
> parse → (OCR) → embed → **named-entity extraction**. Entity extraction runs a local language model
> per document, so indexing a large folder for the first time can take a while. The documents become
> searchable as each one completes.

## 5. The knowledge graph (Entities)

As documents in the **global** corpus are indexed, PersonalAI extracts the named entities they
mention (people, organizations, locations, dates, products, events) into a knowledge graph. The
**Entities** region in Settings → Documents lets you browse them grouped by type, search by name, and
open an entity to see which documents mention it and how it relates to other entities.

Entity extraction is **corpus-global** (an entity can span many documents and folders) and runs only
for the durable corpus — documents attached to a single chat are not added to the graph. It is
best-effort: if extraction fails for a document, the document stays searchable; it just is not added
to the graph.

### NER model & memory management

Entity extraction runs on its **own small, fast local model** — separate from the (larger) chat
model — at a small context window, so it is cheap and fits in memory alongside the chat model.
Configurable:

| Setting | Env | Default | Meaning |
| --- | --- | --- | --- |
| `ner_model` | `PERSONALAI_NER_MODEL` | `qwen3:14b` | the local model used for NER |
| `ner_num_ctx` | `PERSONALAI_NER_NUM_CTX` | `8192` | NER context window (KV cache is the main memory driver) |
| `ner_memory_fraction` | `PERSONALAI_NER_MEMORY_FRACTION` | `0.75` | max share of system RAM a NER load may need |

**Memory-aware loading.** Ollama is often shared with other processes. Before loading the NER model,
PersonalAI checks the **global** Ollama load (`/api/ps`) against the `ner_memory_fraction` budget and
only proceeds if the model is already resident or fits **without evicting anything**. If there isn't
room, NER is **deferred** — the document stays searchable, it's just not added to the graph yet, and
a later re-sync / re-extract retries. It never evicts a model that has a task running (Ollama
guarantees this server-side), and it never sends a document off-device.

For a shared Ollama box, these server-side env vars complement the above (set where Ollama runs):

```
OLLAMA_MAX_LOADED_MODELS=2     # chat + NER
OLLAMA_NUM_PARALLEL=1          # 1 request/model -> smallest KV cache
OLLAMA_KV_CACHE_TYPE=q8_0      # halve KV memory (needs flash attention)
OLLAMA_FLASH_ATTENTION=1
OLLAMA_KEEP_ALIVE=5m
```

On Apple Silicon, the 75% default mirrors Metal's working-set limit; if you need more headroom you
can raise it with `sudo sysctl iogpu.wired_limit_mb=<MB>` (unsupported by Apple, resets on reboot).

## 6. Privacy & security

- **Local only.** Parsing, OCR, embeddings, and entity extraction use your local models; the folder
  sync is hard-restricted to a loopback provider and fails closed rather than ever sending a document
  to the network.
- **Scoped access.** Only folders you explicitly grant are read. Every file is re-checked to be
  inside the granted root (symlink escapes are blocked), and secrets/VCS/dependency directories
  (e.g. `.env`, `*.pem`, `.git/`, `node_modules/`) are excluded by default.
- **Tenant isolation.** All documents, folder state, and entities are Row-Level-Security scoped to
  your tenant.

## 7. Troubleshooting

- **"folder not found" / "not a directory":** the path must be an absolute path to an existing,
  readable directory on the machine running the backend.
- **A folder stays "indexing" for a long time:** expected for large folders on the first pass — the
  per-document entity-extraction step is the slow part (see the heads-up in §4).
- **A file shows an error:** open the folder's tree and the file row shows the reason (unsupported
  type, too large, unreadable/locked, or an extraction failure). Fix it on disk and the next scan
  re-indexes it.
- **Nothing indexes / 503:** folder sync needs the database — confirm Postgres is running
  (`make db`).
