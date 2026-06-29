# Knowledge viz, agent collaboration graph, 3-section shell (0.9.0)

Shipped in the 0.9.0 cycle (all merged to main):

- **Settings -> Knowledge** (`KnowledgeGraph.tsx`, `KnowledgeCorpus.tsx`, `knowledgeUi.tsx`): KAG force-graph (react-force-graph-2d) with on-canvas labels for focus + top-degree neighbors (pure `pickLabeledNodeIds`), Fit/Reset camera (`ForceGraph2D` ref + zoomToFit), size/edge legend, cold-start Top-entities launcher, and visual polish (focus halo, white node strokes, label halos; hover via a tiny scoped `<style>` kg-chip/kg-btn since inline styles can't do `:hover`). Corpus: Type/Size/Entities columns, sortable headers + search + status filter (pure `sortFilterDocs`), stat cards (corpus size + amber "N not indexed"), entity-type breakdown bar. Exact counts come from `GET /api/v1/entities/stats` + per-doc `entity_count` (NOT a client sample). Reuse `TYPE_META`/`TypeBadge`/`formatBytes`/status hues from knowledgeUi/folderUi.

- **Settings -> Agents collaboration graph** (`AgentGraph.tsx`): deterministic hand-drawn SVG (NOT force-graph) that redraws off props as the agentic settings toggle — single / multi (planner->researcher->critic->[verifier]->[gate]->answer with dashed revise + replan loops) / custom placeholder. Fact-check edge attaches to the last judge. Verifier color = rose `#db2777` in `agentColors.ts` (distinct from tool violet); used in the verification trace row + ActivityTimeline (identity rose, verdict stays green/red).

- **3-section app shell** (`Chat.tsx`): the flex column is title (header) / body / status. The body is the ONE scroll region (`flex:1; minHeight:0; overflowY:auto`, `data-testid="app-body"`); the security/status note is pinned (`flexShrink:0` + top border). Fixes the status note riding over long Settings content.

Gates: `tsc --noEmit` (= `pnpm lint`) + `vitest run`; full UI suite is 377 tests. No ESLint, no coverage gate. Extract pure helpers for unit tests.
