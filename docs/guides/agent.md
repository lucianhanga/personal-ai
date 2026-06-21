# The agent (single-agent loop + multi-agent graph)

PersonalAI has two agent runtimes that share the same safety seams. Which one runs is set by the
per-tenant **agent mode** (`agent_mode`), configured in the UI **Settings → Agents** panel:

- **single** (M6, default) — the **single-agent loop**: with **Use tools** on, the model calls
  tools, reads the results, reasons, and continues until a final answer — all streamed live.
- **multi** (M8.1, ADR-0012) — the **multi-agent graph**: a LangGraph graph **planner → researcher
  → critic → finalize** with a **bounded reflection loop** and an optional **durable human approval
  gate** before the answer is committed. See [Multi-agent graph (M8.1)](#multi-agent-graph-m81).
- **custom** — reserved for user-defined agents (future); behaves like the configured graph today.

The legacy `agent_graph_enabled` boolean still works for env-based config and maps to
`agent_mode="multi"`, but the mode selector in **Settings → Agents** is now the user-facing control.

Either way, every tool call goes through the **gateway** (permissions, egress allowlist, schema
validation, risk approval, audit), so acting autonomously stays safe. LangGraph is the orchestration
engine only — graph nodes call PersonalAI's own `ModelProvider` and `ToolGateway` seams directly;
LangChain's model/tool abstractions are not used (ADR-0012 load-bearing invariant).

## What you can do

- Ask it to **act**: *"What is 23 × 19?"* → it calls the **calculator** and answers **437**.
- Ask it to **search**: *"Search the web for X and summarize"* → it calls **web_search** (egress-gated
  to DuckDuckGo) and answers with sources.
- Turn on **Reasoning** to have it think before answering; the reasoning streams and is saved.

## How it works

```
user → assemble context (RAG + memory + STM) → agent loop:
        ┌─> model.stream(tools, think)
        │      ├─ reasoning tokens  ──► live (Reasoning)
        │      ├─ answer tokens     ──► live
        │      └─ tool_calls        ──► gateway.invoke(...) ──► tool result ─┐
        └───────────────────────────────(feed result back, loop)───────────┘
        → final answer
```

- The loop **streams each model turn**, so reasoning and the answer arrive token-by-token; tool calls
  are parsed out of the stream (Ollama + OpenAI).
- Tool results are fed back as native **TOOL-role** messages so the model treats them as data.
- It stops at a final answer or a **max-iteration** guard.
- The ordered timeline (reasoning → tool call → result → …) is shown per message under **Details**
  and **persisted** (`meta.trace`), so reopening a conversation keeps it.

### Query contextualization (follow-ups)

A follow-up like *"and the second one?"* has no meaning on its own, so before retrieval the backend
rewrites the **last** user message into a **standalone, self-contained request** using recent
history (one extra tool-free model call) and uses that to anchor **RAG/memory retrieval and tool
queries**. The rewrite keeps the user's language and intent; it does **not** replace the original
question that drives the answer. It's **skipped for a first or standalone question** (no prior
turn), so a plain one-shot question pays no extra latency. When it fires, the assembled context
view shows an **Interpreted request** line. The model is also instructed to **reply in the same
language the user used**.

## Safety

- Tools run through the **gateway**: least-privilege permissions, **egress allowlist**, JSON-Schema
  I/O, **risk approval** (HIGH/CRITICAL need *approve high-risk*), timeout, and an append-only
  **audit** (the **Activity** panel, per chat).
- Tool output is **untrusted data**, never instructions.

## Multi-agent graph (M8.1)

With `agent_mode = "multi"` (Settings → Agents, or `PERSONALAI_AGENT_MODE=multi`), a chat turn runs
as a LangGraph graph instead of the single loop. The graph is defined in
`core/src/personalai_core/graph.py`:

```
START → planner → researcher → critic → [revise? → researcher] → [human_gate] → finalize → END
```

- **planner** — one tool-free model call producing a short 1–3 bullet plan; emits a `plan` step.
  It's told a tool-capable researcher will execute the plan, so it never claims a lack of tools.
- **researcher** — the single-agent loop (`run_agent`), informed by the plan; streams reasoning,
  answer, and tool steps exactly as the M6 loop does. **It is the only agent that uses tools.**
- **critic** — one model call reviewing the answer against the request; it begins with `OK` or
  `REVISE` and adds a short explanation, then emits a `critique` step. The critique streams to the
  **reasoning pane only and never modifies the answer** — the agents' result stands; their review
  is shown, not applied.
- **bounded reflection loop** — on a `REVISE` verdict the researcher **retries once** (the critique
  is fed back so it takes a different path); `MAX_ATTEMPTS = 2` (initial attempt + one retry), after
  which the turn proceeds regardless of the verdict.
- **human_gate** (only when the durable gate is on) — suspends the turn for human approval.
- **finalize** — emits the single terminal answer.

The **current date is injected up front** (a system message) so every agent is date-aware and
won't dismiss recent dates or facts as fabricated.

Because the graph adds a planner call and a critic call (and possibly one researcher retry) around
the normal loop, **it makes ~2+ extra model calls per turn and is noticeably slower**. Keep it on
`single` for quick chat; switch to `multi` when you want a checked, plan-then-review answer.

### Per-agent configuration (Settings → Agents)

Each agent (planner / researcher / critic) has an **editable system prompt** and, for the
**researcher only**, **per-agent tool/MCP scoping** (which tools it may call). Defaults ship in
`DEFAULT_AGENT_PROMPTS`; an empty override falls back to the default for that agent. Configure these
in the UI **Agents** panel, or over the API:

```bash
curl -H "Authorization: Bearer demo" http://127.0.0.1:8765/api/v1/agents/config   # roster + defaults + saved overrides
curl -X PUT  http://127.0.0.1:8765/api/v1/agents/config -H "Authorization: Bearer demo" \
  -H "Content-Type: application/json" -d '{"agents":[{"name":"researcher","prompt":"..."}]}'
```

The config is per-tenant; unknown agent names are rejected. Prompt overrides and the researcher's
disabled tools are loaded **only** on the graph (`multi`) path — `single` mode uses all tools and no
agent personas.

### What you see in the UI

With the graph on, the per-message **Details** trace shows the extra steps, color-coded (no emoji):

| Step | Color | Meaning |
|---|---|---|
| Planner | blue | the plan |
| Thinking | gray | researcher reasoning |
| Tool | violet | a gateway tool call |
| Result | green / red | tool success / failure |
| Critic | amber | the critique |
| Verify | green / red | verification verdict (M8.2) |

### Durable human approval gate

`PERSONALAI_AGENT_HUMAN_GATE=true` (requires `PERSONALAI_AGENT_GRAPH_ENABLED=true` **and** a
reachable Postgres) inserts the `human_gate` node before `finalize`. Each turn then **suspends after
the critic** and waits for you to approve or reject the answer:

1. The backend emits an `approval_request` SSE frame (`{run_id, reason, answer, critique}`) and the
   stream ends **without** a `done` frame.
2. The run state is persisted in a **tenant-scoped checkpoint** (`TenantCheckpointSaver`, migration
   `0014_agent_checkpoints.sql`, Postgres RLS), so it survives restarts and stays tenant-isolated.
3. The UI shows the answer + critique with **Approve / Reject** controls.
4. Resume with `POST /api/v1/chat/{run_id}/resume` and body `{decision, conversation_id?}`. The
   resume runs under a **fresh `SecurityContext`** (with CSRF in hosted mode); the checkpoint loads
   **only under the resumer's tenant**, so a foreign `run_id` returns **404** (cross-tenant resume
   is impossible).

The user-visible flow is: **plan → answer + tool steps → critique → approve/reject → final answer.**

### Enabling it

Set it per-tenant in **Settings → Agents** (preferred), or via env for the boot default:

```bash
# Multi-agent graph only (no gate; works without a DB):
PERSONALAI_AGENT_MODE=multi make run-backend

# Graph + durable human gate (needs Postgres):
PERSONALAI_AGENT_MODE=multi PERSONALAI_AGENT_HUMAN_GATE=true make run-backend
```

`agent_mode` defaults to **single** and the human gate to **off**. The legacy
`PERSONALAI_AGENT_GRAPH_ENABLED=true` still maps to `multi` for backward compatibility. See
[backend API](../reference/backend-api.md) for the exact SSE frames and the resume endpoint, and
[ADR-0012](../architecture/adr/0012-langgraph-orchestration.md) for the design.

## Configuration

Per-tenant preferences (model, agent mode, behaviour, embeddings, egress, timeout) are saved via
`GET`/`PUT /api/v1/settings` and overlay the boot config for that tenant; an unset field inherits the
deployment default. The env vars below set those deployment defaults (all prefixed `PERSONALAI_`).

| Setting | Default | Notes |
|---|---|---|
| **Use tools** (`use_tools`) | on | enable autonomous tool use |
| **approve high-risk** (`approve_tools`) | on | allow HIGH-risk tools (e.g. `http_fetch`) this turn |
| **Reasoning** (`think`) | off | ask the model to think first (slower; needs a `thinking` model) |
| `PERSONALAI_AGENT_MODE` | single | `single` / `multi` / `custom` — which agent runtime runs (per-tenant in Settings → Agents) |
| egress | off | `PERSONALAI_EGRESS_ENABLED=true` + `PERSONALAI_ALLOWED_EGRESS_HOSTS=…` (also per-tenant in Settings → Network) |
| `PERSONALAI_OLLAMA_NUM_CTX` | 32768 | bounds the context window (KV cache) |
| `PERSONALAI_AGENT_MAX_ITERATIONS` | 8 | safety cap on the single-agent loop |
| `PERSONALAI_AGENT_TIMEOUT_SECONDS` | 300 | whole-turn wall-clock cap (30–3600); the turn fails with a timeout on expiry |
| `PERSONALAI_AGENT_GRAPH_ENABLED` | false | legacy flag; `true` maps to `agent_mode=multi` |
| `PERSONALAI_AGENT_HUMAN_GATE` | false | with the graph + a DB: suspend each turn for approve/reject |
| `PERSONALAI_AGENT_ACCURACY_MODE` | standard | `standard` / `accurate` — verification-ladder depth (M8.2) |

## Verify against a real model

```bash
PERSONALAI_OLLAMA_IT=1 uv run pytest apps/backend/tests/test_agent_integration.py -q
```
(Opt-in; skipped in CI. Needs a local Ollama with a `tools`-capable model, e.g. qwen3.)

## What's next

**M8.2** builds on the graph with a **tiered verification ladder**, **bounded schema-repair**, and
an **accuracy mode** (`PERSONALAI_AGENT_ACCURACY_MODE`) that controls how deeply answers are
verified — surfaced in the trace as the green/red **Verify** step. Third-party **MCP servers** (M7)
plug into the same gateway as additional tool sources — sandboxed (ADR-0007) — so "ask it to search
/ browse / act" extends to the whole MCP ecosystem in either runtime.
