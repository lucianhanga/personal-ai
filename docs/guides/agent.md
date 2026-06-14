# The agent (single-agent loop + multi-agent graph)

PersonalAI has two agent runtimes that share the same safety seams:

- **Single-agent loop** (M6, default): with **Use tools** on, the model calls tools, reads the
  results, reasons, and continues until a final answer — all streamed live.
- **Multi-agent graph** (M8.1, ADR-0012, opt-in): a LangGraph graph **planner → researcher →
  critic → finalize**, with an optional **durable human approval gate** before the answer is
  committed. See [Multi-agent graph (M8.1)](#multi-agent-graph-m81) below.

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

## Safety

- Tools run through the **gateway**: least-privilege permissions, **egress allowlist**, JSON-Schema
  I/O, **risk approval** (HIGH/CRITICAL need *approve high-risk*), timeout, and an append-only
  **audit** (the **Activity** panel, per chat).
- Tool output is **untrusted data**, never instructions.

## Multi-agent graph (M8.1)

When `PERSONALAI_AGENT_GRAPH_ENABLED=true`, a chat turn runs as a LangGraph graph instead of the
single loop. The graph is defined in `core/src/personalai_core/graph.py`:

```
START → planner → researcher → critic → [human_gate] → finalize → END
```

- **planner** — one tool-free model call producing a short 1–3 bullet plan; emits a `plan` step.
- **researcher** — the single-agent loop (`run_agent`), informed by the plan; streams reasoning,
  answer, and tool steps exactly as the M6 loop does.
- **critic** — one model call reviewing the answer against the request (gaps, errors, unsupported
  claims); emits a `critique` step. It does **not** rewrite the answer.
- **human_gate** (only when the durable gate is on) — suspends the turn for human approval.
- **finalize** — emits the single terminal answer.

Because the graph adds a planner call and a critic call around the normal loop, **it makes ~2 extra
model calls per turn and is noticeably slower**. Keep it off for quick chat; turn it on when you
want a checked, plan-then-review answer.

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

```bash
# Multi-agent graph only (no gate; works without a DB):
PERSONALAI_AGENT_GRAPH_ENABLED=true make run-backend

# Graph + durable human gate (needs Postgres):
PERSONALAI_AGENT_GRAPH_ENABLED=true PERSONALAI_AGENT_HUMAN_GATE=true make run-backend
```

Both default to **off**. See [backend API](../reference/backend-api.md) for the exact SSE frames and
the resume endpoint, and [ADR-0012](../architecture/adr/0012-langgraph-orchestration.md) for the
design.

## Configuration

| Setting | Default | Notes |
|---|---|---|
| **Use tools** (`use_tools`) | on | enable autonomous tool use |
| **approve high-risk** (`approve_tools`) | on | allow HIGH-risk tools (e.g. `http_fetch`) this turn |
| **Reasoning** (`think`) | off | ask the model to think first (slower; needs a `thinking` model) |
| egress | off | `PERSONALAI_EGRESS_ENABLED=true` + `PERSONALAI_ALLOWED_EGRESS_HOSTS=…` for network tools |
| `PERSONALAI_OLLAMA_NUM_CTX` | 32768 | bounds the context window (KV cache) |
| `PERSONALAI_AGENT_MAX_ITERATIONS` | 8 | safety cap on the single-agent loop |
| `PERSONALAI_AGENT_GRAPH_ENABLED` | false | opt into the M8.1 multi-agent graph (planner/researcher/critic) |
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
