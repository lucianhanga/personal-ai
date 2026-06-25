---
name: project-rag-timeline
description: #437 RAG pipeline steps (indexing/retrieval/ner) presentation in ActivityTimeline — new kinds, hues, RAG filter, contract alignment with architect
metadata:
  type: project
---

#437 surfaces RAG pipeline steps in the chat ActivityTimeline as three new `NodeKind`s extending the #424 trace-item superset. Design posted as a comment on #437; implementation waits on PR4/#436.

**Why:** RAG work (doc indexing, hybrid retrieval, future NER) was invisible; user wants it shown alongside the #424 resource activities and the agent trace.

**How to apply (presentation decisions, reuse these):**
- Three categories + AA-verified hues on white: `indexing` `#8a6d00` (amber-olive), `retrieval` `#1558b0` (royal indigo, deeper than context's `#4a90d9`), `ner` `#a21caf` (fuchsia-plum). Retrieval fallback if confused with context: `#5b21b6`.
- ONE combined `RAG` filter chip (not three) — chip row already 5 wide; NER dormant. Internally 3 NodeKinds (distinct dots), grouped in `visibleNodes`.
- Reuse ResourceIO/ToolIO disclosure shell. Ordering in `buildNodes`: after resource loop, before the Context-assembled node (retrieval FEEDS context): resource -> indexing -> retrieval -> ner -> context -> agent.
- ner ships DORMANT: renderer adds the branch but emits no chip until Phase 6's `_emit_ner` hook fires.

**Architect contract (agentic-ai-architect owns it, see [[project_panels_redesign]]):** a "context prelude" prepended to the single assistant `meta["trace"]` (NOT a separate user-turn cluster, NOT a new persist key). Live == replay. Field names to render against (theirs win): indexing `{ref, chunks, ms, status?, error?}`; retrieval `{query, top_k, hits, scope:"global"|"conversation"|"union", ms, citations:[{source,score}]}` — citations are source+score ONLY, no snippet, capped <=8 so no expander needed; ner `{count, types:[{type,count}]}`.

New file for impl: `apps/ui/src/RetrievalIO.tsx` (citation `<ol>` + aria-hidden score fill bar; numeric score is the accessible value). Extend `TraceItem.kind` in api.ts with `indexing|retrieval|ner` + the additive fields.

0-hit retrieval is deliberate SIGNAL (architect emits `hits:0`): show `No passages retrieved ({scope})`, pill stays `done` (not error).
