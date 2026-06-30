# Settings → Agents rework: model-stack defaults + decoupled approval gates

Design deliverable (2026-06-30). Three related changes to the **Settings → Agents** panel
(`apps/ui/src/Agents.tsx`) and its backing settings stack. Approved decisions are marked **[locked]**;
code lands after sign-off. Implementation order: **A → B → C**.

Related: ADR-0012 (LangGraph orchestration), ADR-0013 (egress-approval gate), the #491 layered-model-stack
epic (RAG embed/rerank #492, GLiNER NER #493).

## Motivation

While testing the rich-output `image_search` tool, three problems surfaced in Settings → Agents:

1. The **"Defaults"** section exposes a single global **Provider** dropdown that in fact only sets the
   *chat* model's provider (`model_provider`), does nothing for embeddings (own `embed_provider`), and
   is meaningless for the reranker/NER tasks — misleading.
2. The same section only configures the **chat** model. The product needs per-task model defaults for
   **every** AI/LLM task in the stack: chat/validation, RAG embeddings, reranking, NER/relation extraction.
3. Two existing settings — `default_reasoning` and `agent_verifier_check` — **silently fail to persist**
   (revert on reload).
4. The durable egress allow/deny pause (ADR-0013) is **coupled** to the answer-approval gate via the
   single `agent_human_gate` flag, so there is no way to get the egress pause without also enabling
   per-turn answer approval. The checkbox label describes only answer approval, hiding the egress role.

---

## A. Model-stack defaults panel **[locked]**

Replace the flat "Defaults" block (and delete the standalone global **Provider** selector) with **one
row per AI/LLM task**. Each row is a **single combined `provider / model` dropdown** — provider and
model are never shown as separate controls.

```
Model stack
┌────────────────────────────────────────────────────────────────────┐
│ Chat / validation   [ ollama / qwen3.6:27b          ▾ ]  [reasoning ▾]│
│ RAG embeddings      [ ollama / qwen3-embedding:0.6b  ▾ ]               │
│ Reranker            [ Off ▾ | curated HF ids… ]                       │
│ NER / relations     [ ollama / qwen3:14b            ▾ ]               │
└────────────────────────────────────────────────────────────────────┘
```

### Combined dropdown mechanics
"Combined" is presentation only — the contract keeps provider and model as **separate fields**. Each
option's label is `"<provider> / <model>"`; selecting it writes **both** underlying fields atomically:

| Task | Underlying fields set by the dropdown | Reasoning control |
|------|---------------------------------------|-------------------|
| Chat / validation | `model_provider` + `default_model` | separate `default_reasoning` select (chat-only knob) |
| RAG embeddings | `embed_provider` + `embed_model` | — |
| Reranker | `rerank_enabled` + `rerank_model` (see below) | — |
| NER / relations | `ner_model` (provider fixed = ollama) | — |

The global **Provider** dropdown is **removed**; provider now lives inside each option's label.
The empty/default option reads **"Use server default"** everywhere (no "Inherit" wording in this panel —
the per-agent cards keep their legitimate "Inherit" since they genuinely inherit from these defaults).

### Option population — "what's actually available" **[locked: D]**

| Task | Source of options | Capability filter |
|------|-------------------|-------------------|
| Chat / validation | `/api/v1/models?provider=` for each of `ollama`, `openai_compat` | `capabilities.text` |
| RAG embeddings | same, both providers | `capabilities.embeddings` |
| NER / relations | `/api/v1/models?provider=ollama` | `capabilities.text` |
| Reranker | **curated static list + the currently-configured id** | n/a |

- The chat/embeddings/NER lists come from each provider's `list_models()` (already exposed by
  `/api/v1/models`, which returns per-model capability flags). The UI fans out one request per
  registered provider (from `/api/v1/providers`) and merges, tagging each option with its provider.
- **Reranker [locked]:** `hf_reranker` is a torch model loaded on demand — it is **not** a registered
  provider and has **no** `list_models`. The dropdown is therefore a **curated hardcoded list** of
  known-good reranker ids (e.g. `Qwen/Qwen3-Reranker-0.6B`, `BAAI/bge-reranker-v2-m3`), **always
  including** whatever `rerank_model` is currently set to. The first option is **"Off"** → sets
  `rerank_enabled = false`; choosing a model sets `rerank_enabled = true` + `rerank_model`.
- **NER [locked]:** populated from Ollama text models today (matches the current Ollama `ner_model`).
  **Revisit when #493 GLiNER2 lands** — GLiNER is a HF/spaCy extractor, not an Ollama chat model, so
  this row's source will change. Documented as a known follow-up, not built for GLiNER now.

---

## B. Decouple approval gates **[locked]**

Split the single `agent_human_gate` into **two independent toggles** under an **"Approvals"**
subsection (multi-agent mode only):

- **Answer approval** — `agent_human_gate` (existing): pause each turn to approve/reject the final
  answer before finalizing.
- **Network egress approval** — `agent_egress_gate` (**new**, default **off** [locked]): pause to
  allow/deny when a tool calls a non-allowlisted host, then auto-resume the blocked call (ADR-0013).

### Backend threading
Today the durable gate (`gate_on`, `app.py:1861`) creates a checkpointer **iff** `agent_human_gate`,
and both the egress gate and the human gate are wired off `checkpointer is not None`
(`graph.py:736`, `1013`, node/edge setup ~`975`–`1051`). Decouple:

1. `core/config.py`: add `agent_egress_gate: bool = False` (+ `AGENT_EGRESS_GATE` env, bool-fields set).
2. `app.py`: compute `human_gate_on` and `egress_gate_on` independently; create the checkpointer when
   **either** is on; pass two booleans (`human_gate`, `egress_gate`) into `run_turn`.
3. `turn.py run_turn` → `graph.py run_graph` → `_build_graph`: add `human_gate: bool`, `egress_gate: bool`
   params and thread them through.
4. `_build_graph`: compute `human_enabled = human_gate and checkpointer is not None` and
   `egress_enabled = egress_gate and checkpointer is not None`. Insert the `human_gate` node + edge and
   set `gate_or_finalize` from `human_enabled`; insert the `egress_gate` node + researcher routing from
   `egress_enabled`; the researcher's gate-vs-degrade branch (`graph.py:736`) keys on `egress_enabled`.
5. Automated runs (`app.py:2554`) set **both** flags false. Resume endpoints (`app.py` ~2360/2512)
   rebuild graph topology from **both** flags so the resumed graph matches the checkpointed one.

### UI / graph diagram
- Two checkboxes with honest labels (answer approval; network egress approval).
- `AgentGraph.tsx` "gate" node logic continues to reflect `agent_human_gate` for the answer gate.

---

## C. Persistence / plumbing fix **[locked: after A & B]**

Root cause of the revert bug: `storage/postgres/.../settings_store.py` `_FIELDS` (the shared
SELECT/INSERT/RETURNING column list) **omits** `default_reasoning` and `agent_verifier_check`, so
`upsert` never writes them and `get` never reads them. They exist in the `TenantSettings` contract and
the UI, but the store drops them.

A already forces most of this plumbing, because `ner_model`, `rerank_enabled`, and `rerank_model` are
**not in the `TenantSettings` contract or the store at all** and must be added. The per-field checklist:

1. `TenantSettings` contract (`contracts/`) — add field (if missing).
2. `settings_store._FIELDS` — add column name.
3. **DB migration** — `ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS …` (verify which already
   exist; `default_reasoning`/`agent_verifier_check` columns may have been migrated but never wired into
   the store — confirm before adding).
4. `apps/ui/src/api.ts` `TenantSettings` type — add field.
5. UI control + handler in `Agents.tsx`.

### Fields touched by this rework

| Field | Contract | Store `_FIELDS` | DB column | api.ts | Status |
|-------|:--------:|:---------------:|:---------:|:------:|--------|
| `model_provider`, `default_model` | ✓ | ✓ | ✓ | ✓ | exists (chat row) |
| `embed_provider`, `embed_model` | ✓ | ✓ | ✓ | ✓ | exists (embeddings row) |
| `default_reasoning` | ✓ | **add** | verify | ✓ | **C — bug** |
| `agent_verifier_check` | ✓ | **add** | verify | ✓ | **C — bug** |
| `agent_egress_gate` | **add** | **add** | **add** | **add** | **B — new** |
| `ner_model` | **add** | **add** | **add** | **add** | **A — new** |
| `rerank_enabled` | **add** | **add** | **add** | **add** | **A — new** |
| `rerank_model` | **add** | **add** | **add** | **add** | **A — new** |

---

## Test plan
- Backend: settings round-trip (upsert→get) for every field above; gate matrix (`human`×`egress` ∈ 4
  states) drives checkpointer creation + graph topology; egress block degrades inline when
  `egress_gate` off, pauses+auto-resumes when on; resume rebuilds matching topology.
- UI: combined-dropdown writes both provider+model; "Off" reranker option clears `rerank_enabled`;
  per-task option lists filter by capability; persistence survives remount; two gate toggles independent.
- `make lint typecheck test js` green; supply-chain unaffected (no new deps).

## Deferred / not chosen
- hf_reranker `list_models` endpoint (rejected in favor of the curated list).
- NER row redesign for GLiNER2 (#493).
- A dedicated validation-model field (chat + validation share `default_model` today).
