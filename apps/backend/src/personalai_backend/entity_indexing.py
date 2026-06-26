"""Best-effort NER indexing of a GLOBAL document's entities into the KAG store (#451).

Ties the core LLM-NER extractor to the entity store. Idempotent (re-extraction purges the document's
prior mentions first, so counts never double) and best-effort (NER must never fail or block an
ingest). Runs only for the global corpus -- the callers gate on global scope.
"""

from __future__ import annotations

import logging

from personalai_contracts.ports import ModelProvider
from personalai_core.entity_extraction import extract_entities
from personalai_storage_postgres import PgEntityStore

logger = logging.getLogger(__name__)


async def index_document_entities(
    text: str,
    document_id: str,
    *,
    store: PgEntityStore,
    provider: ModelProvider,
    model: str,
) -> None:
    """Extract entities from a global document and write them (entities + mentions + edges).

    Best-effort: swallows all errors (a failed NER pass leaves the document indexed for retrieval,
    just without entities). Idempotent: purges the document's prior mentions before re-inserting, so
    a re-sync of the same file does not inflate counts. Entities repeated within the document are
    folded so ``mention_count`` and the mention's ``occurrences`` stay consistent.

    Data-safety (#464): extraction runs BEFORE the purge, and the purge runs ONLY after a SUCCESSFUL
    extraction. Previously the purge ran first, so a failed or timed-out extraction (e.g. a slow
    cold-load of a large model exceeding the client timeout) deleted the document's existing
    entities and wrote nothing back -- silently wiping the KAG. Now a failed extraction leaves prior
    entities untouched; only a result we actually have replaces them."""
    try:
        extracted = await extract_entities(text, provider=provider, model=model)
    except Exception as exc:  # noqa: BLE001 - best-effort; a failed pass MUST keep prior entities
        logger.warning(
            "entity extraction failed for document %s (prior entities kept): %s", document_id, exc
        )
        return

    try:
        # Extraction succeeded (possibly empty) -> now it is safe to replace this document's prior
        # mentions. An empty result intentionally clears stale entities (the document genuinely has
        # none now); a FAILED extraction returned above without touching anything.
        await store.purge_document_entities(document_id)
        if not extracted.entities:
            return

        # Fold duplicates within this document by the canonical (type, normalized-name) key.
        grouped: dict[tuple[str, str], tuple[str, int]] = {}
        for ent in extracted.entities:
            norm = " ".join(ent.name.strip().lower().split())
            if not norm:
                continue
            display, count = grouped.get((ent.type, norm), (ent.name.strip(), 0))
            grouped[(ent.type, norm)] = (display, count + 1)

        ids_by_norm: dict[str, str] = {}  # normalized name -> entity id (to resolve relations)
        for (etype, norm), (display, count) in grouped.items():
            entity_id = await store.upsert_entity(type=etype, name=display, occurrences=count)
            await store.add_mention(entity_id=entity_id, document_id=document_id, occurrences=count)
            ids_by_norm[norm] = entity_id

        for rel in extracted.relations:
            src = ids_by_norm.get(" ".join(rel.src.strip().lower().split()))
            dst = ids_by_norm.get(" ".join(rel.dst.strip().lower().split()))
            if src and dst:
                await store.add_edge(src_entity_id=src, relation=rel.relation, dst_entity_id=dst)
    except Exception as exc:  # noqa: BLE001 - best-effort; NER never fails an ingest
        logger.warning("entity indexing failed for document %s: %s", document_id, exc)
