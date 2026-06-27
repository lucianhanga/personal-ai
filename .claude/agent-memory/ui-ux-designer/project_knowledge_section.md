---
name: project-knowledge-section
description: Design for the Settings > Knowledge section — KAG (entity/document graph) + RAG (corpus + retrieval explorer) visualizations, palette, rendering approach, backend API gaps
metadata:
  type: project
---

Designed a new **Knowledge** section in `SettingsView.tsx` (section rail), inserted AFTER Memory, BEFORE Network. Two sub-tabs: **Graph** (KAG) and **Corpus** (RAG). Extends, does NOT duplicate, the existing `EntityBrowser.tsx` (currently a Documents region).

**Data reality (drives every decision):** entity-entity edges exist in schema but are SPARSE/empty (entities-only extraction). So the real graph is **bipartite entity<->document** + **co-occurrence** (entities sharing a doc). Scale today ~108 entities / ~14 docs; design for hundreds -> low thousands.

**KAG decisions:**
- PRIMARY interaction = **focus+context ego-graph / expand-on-demand**, NOT a full force-directed hairball. Research: node-link readable only to a few hundred-~1000 nodes before hairball (Cambridge Intelligence; arXiv 1809.00270). Land on overview+list; select entity/doc -> render its neighborhood capped ~300 nodes with "expand more".
- Bipartite: entities = CIRCLE colored by type; documents = SQUARE/slate. Shape distinguishes the two node classes WITHOUT color (color-blind safe). Offer "collapse documents -> entity co-occurrence projection" toggle (the meaningful entity-cluster view given sparse direct edges).
- Accessibility MANDATE (research consensus, Cambridge Intelligence / MIT Vis / arXiv 2311.04502): always pair the canvas with a textual/list/table alternative. Reuse the EntityBrowser list as that fallback (same /entities API). Canvas is `aria-hidden`; keyboard + SR drive the list.
- Rendering: MVP `react-force-graph` (Canvas) for ego-graphs (tens of nodes, trivial). Whole-corpus overview at hundreds-low-thousands also fine on Canvas. Only move to sigma.js/graphology (WebGL) if >~5k nodes. Don't use SVG/d3 DOM-per-node at scale.

**RAG decisions:**
- Corpus Overview (MVP): stats (docs, chunks, entities, embedding model/dim, avg chunks/doc) + per-doc table (chunk_count, indexed status, entity count, coverage flags). Mostly derivable from fetchFiles + /entities.
- **Retrieval Explorer / playground** (MVP, highest value per research/Arize Phoenix): query box -> standalone retrieve (NOT a chat turn) -> ranked chunks w/ snippet, RANK (primary), score (secondary relative bar), source_kind + merged_from provenance. RRF fused scores are NOT physically meaningful -> show rank+provenance, not absolute score (OpenSearch/Azure/MongoDB RRF docs).
- Chunk inspector: doc -> its chunks. Needs new endpoint.
- **2D embedding map (UMAP/t-SNE): RECOMMEND AGAINST as core feature.** distill.pub "Misread t-SNE" + arXiv 2506.08725: cluster size/inter-cluster distance are meaningless, local-not-global. Optional debug-only enhancement, clearly labeled "approximate".

**Backend API gaps (must expose; flag to backend-api-architect / ui-developer):**
- GET /entities/{id}/neighborhood -> docs + co-occurring entities w/ weights, capped (for ego-graph).
- GET graph nodes+edges for overview (bipartite + co-occurrence weights) OR client-derive from /entities + per-doc entities.
- GET /documents/{id}/entities (entities per document) — only entities-per... wait we have docs-per-entity via detail; need the inverse + per-doc chunk list.
- GET /documents/{id}/chunks -> chunk text (chunk inspector).
- POST /retrieve {q, scope, top_k} -> ranked chunks w/ text+score+source_kind (standalone, no chat turn) — currently retrieval only happens inside chat streaming onCitations.
- GET /corpus/stats (optional convenience) -> totals + embedding model/dim.

**Palette (entity-type hues, AA on white, paired with type-letter badge + label, never color-only):** person #1a6fb0, org #6d28d9, location #0d7d7d, date #8a6d00, product #b3431a, event #a21caf, other #555. Document node #334155 (slate). Status: green #1a7f37 ok, red (folderUi RED) error, amber #8a6d00 warn. Reuses entity category fuchsia #a21caf (now = event) and retrieval indigo #1558b0 from [[project-rag-timeline]].

See [[project-ui-architecture]] for SettingsView rail + loading/empty/error trio + testid conventions, [[project-rag-timeline]] for RetrievalIO citation/score-bar pattern to reuse in the Retrieval Explorer.
