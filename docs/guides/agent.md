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
- In the multi-agent graph, a tool call to a **non-allowlisted host** pauses the run for an explicit
  decision via the [egress-approval gate](#2-egress-approval-gate-blocking) instead of silently
  failing.
- Tool output is **untrusted data**, never instructions.

## Multi-agent graph (M8.1)

With `agent_mode = "multi"` (Settings → Agents, or `PERSONALAI_AGENT_MODE=multi`), a chat turn runs
as a LangGraph graph instead of the single loop. The graph is defined in
`core/src/personalai_core/graph.py`:

```
START → planner → [gather → merge →] researcher → [egress_gate → researcher]
        → critic → (replan → planner) | (revise → researcher) | [verifier →] [human_gate]
        → finalize → END
```

- **planner** — one tool-free model call producing a short 1–3 bullet plan; emits a `plan` step.
  It's told a tool-capable researcher (with RAG / KAG / memory) will execute the plan, so it never
  claims a lack of tools or refuses a private-data question. When **multiple retrieval sources** are
  available it also emits a `SourcePlan` (which sources to query).
- **gather → merge** (only when retrieval sources exist) — **multi-source retrieval** (#420): the
  `gather` node fans out over the planner's chosen `RetrievalSource`s in **bounded parallel**, and
  `merge` fuses the results with **cross-source RRF** + a per-source token budget into one evidence
  set, streaming **unified citations** tagged with `source_kind` / `merged_from`. The fused evidence
  is kept in a distinct state key so a later researcher answer can't clobber it — the critic and
  verifier judge against it. With no sources these nodes aren't added and the topology is unchanged.
- **researcher** — the single-agent loop (`run_agent`), informed by the plan and grounded on the
  merged evidence; streams reasoning, answer, and tool steps exactly as the M6 loop does. **It is the
  only agent that uses tools** in the loop sense.
- **critic** — one model call reviewing the answer **against the retrieved sources as ground truth**;
  it begins with `OK`, `REVISE`, or `REPLAN` and adds a short explanation, then emits a `critique`
  step. The critique streams to the **reasoning pane only and never modifies the answer** — the
  agents' result stands; their review is shown, not applied. When the critic is the **last judge**
  (standard mode, no verifier downstream) it also runs the shared [judge fact-check](#judge-fact-check).
- **bounded evaluator-optimizer loop** — on a `REVISE` verdict the researcher retries (sound plan,
  poor execution); on a `REPLAN` verdict the graph routes back to the **planner** (the plan itself
  was the fault → re-plan + re-retrieve). Both share `MAX_ATTEMPTS = 2` (initial attempt + one
  retry), after which the turn proceeds regardless of the verdict.
- **verifier** (accurate mode only) — a first-class LLM-judge agent that returns a schema-validated
  `Verdict` and runs the [judge fact-check](#judge-fact-check); a non-`pass` verdict routes one more
  researcher pass (sharing the attempt cap). See [Verification ladder](#verification-ladder-m82).
- **egress_gate** (only when a checkpointer is wired) — if the researcher's tools try to reach a
  **non-allowlisted host**, the run **pauses for egress approval** before that call is allowed. This
  is the second durable gate. See [Durable gates](#durable-gates-answer-approval--egress-approval).
- **human_gate** (only when the durable answer gate is on) — suspends the turn before `finalize`
  for human approval of the answer.
- **finalize** — emits the single terminal answer.

The **current date is injected up front** (a system message) so every agent is date-aware and
won't dismiss recent dates or facts as fabricated.

Because the graph adds a planner call and a critic call (and possibly one researcher retry) around
the normal loop, **it makes ~2+ extra model calls per turn and is noticeably slower**. Keep it on
`single` for quick chat; switch to `multi` when you want a checked, plan-then-review answer.

### Per-agent configuration (Settings → Agents)

Each agent (planner / researcher / critic / **verifier**) has an **editable system prompt** and, for
the **researcher only**, **per-agent tool/MCP scoping** (which tools it may call). The default
prompts are now **source-agnostic** (not tied to a specific source) and ship in
`DEFAULT_AGENT_PROMPTS`; an empty override falls back to the default for that agent. The **Agents**
panel also draws a **live collaboration graph** showing how the configured agents hand off for the
selected agentic design (single / multi / accurate). Configure these in the UI, or over the API:

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
| Verify | rose (verdict word green / red) | the verifier agent's identity; the verdict keeps pass=green / fail=red |

### Durable gates (answer-approval + egress-approval)

The multi-agent graph has **two** durable human-in-the-loop gates. Both use the **same durable
machinery** — a LangGraph `interrupt()` plus the **tenant-scoped checkpoint**
(`TenantCheckpointSaver`, migration `0014_agent_checkpoints.sql`, Postgres RLS), so a suspended run
survives a restart and stays tenant-isolated. Both resume through the **same** endpoint,
`POST /api/v1/chat/{run_id}/resume`, which dispatches on the gate's `reason` **read from the
checkpoint** (never from the request body). On resume, a **fresh `SecurityContext`** is in scope
(with CSRF in hosted mode), the checkpoint loads **only under the resumer's tenant** (a foreign
`run_id` → **404**, cross-tenant resume is impossible), and the run may be resumed **only by the
same subject that started it** (a different subject in the same tenant → **403**).

#### 1. Answer-approval gate

`PERSONALAI_AGENT_HUMAN_GATE=true` (requires `PERSONALAI_AGENT_GRAPH_ENABLED=true` / `agent_mode=multi`
**and** a reachable Postgres) inserts the `human_gate` node before `finalize`. Each turn then
**suspends after the critic** and waits for you to approve or reject the answer:

1. The backend emits an `approval_request` SSE frame (`{run_id, reason:"approve_answer", answer,
   critique}`) and the stream ends **without** a `done` frame.
2. The UI shows the answer + critique with **Approve / Reject** controls.
3. Resume with body `{decision: "approve" | "reject", conversation_id?}`.

The user-visible flow is: **plan → answer + tool steps → critique → approve/reject → final answer.**

#### 2. Egress-approval gate (blocking)

This gate needs **no flag** — it is always armed whenever the graph runs with a checkpointer (a
reachable Postgres). It turns a blocked outbound call into an **explicit, blocking decision** instead
of a silent tool error (ADR-0013):

1. When a researcher tool's outbound call targets a **host that is not on the tenant's egress
   allowlist**, the agent loop yields an engine-agnostic `egress_blocked` event and **returns**
   (it does not re-prompt the model). The graph routes to the `egress_gate` node, which calls
   `interrupt()` to **pause the run durably**.
2. The backend emits an `approval_request` SSE frame with
   `{run_id, reason:"egress_approval", blocked_host, tool, args}` (args are persisted from the
   checkpoint; the SSE payload is whitelisted to exactly these client-facing keys). The stream ends
   without a `done` frame.
3. The UI shows **four** choices:
   - **Allow once** (`egress_allow_once`) — permit this host for **this run only**; the host is
     added to a **non-persisted** config copy.
   - **Allow always** (`egress_allow_always`) — **persist** the host to the **tenant** egress
     allowlist (tenant-scoped + audited) and enable egress, then resume.
   - **Don't allow** (`egress_deny`) — resume with the egress denial; the blocked call returns its
     error to the agent and the turn continues without it.
   - **More info** — reveal the **redacted** outbound args (secret-looking keys — `authorization`,
     `token`, `api_key`, `password`, `cookie`, `bearer`, … — are deep-redacted before display).
4. Resume with body `{decision: <egress verb>, conversation_id?, provider?}`. Because an egress
   resume **re-runs the researcher** (a real model call), the UI sends the turn's original
   `provider` so the retry runs on the same model.
5. On an allow, **only the blocked tool is retried** — the prior succeeded tools are already in the
   checkpointed conversation as TOOL-role messages and **never re-fire**. The run may suspend again
   at a later blocked call.

**Why the gate is durable + server-trusted, not a client toggle:**

- The **blocked host comes from the checkpoint**, never the request body — a client sends only the
  verb, so it cannot smuggle in an arbitrary destination.
- The **per-call SSRF guard still runs after any allow.** Allowing a host only adds it to the
  allowlist set; the tool's public-host check still refuses loopback, RFC1918, link-local/metadata
  (`169.254.169.254`), and other non-public addresses. "Allow always" on a metadata IP is still
  blocked at fetch time.
- The **allowlist write happens in the backend** (tenant-scoped + audited). No graph node touches
  the database — the `egress_gate` node only calls `interrupt()` (ADR-0012 seam: the engine gets no
  privileges of its own).

The user-visible flow is: **plan → researcher hits a blocked host → pause → allow-once / allow-always
/ deny / more-info → (on allow) retry just that call → continue → answer.**

### Enabling it

Set it per-tenant in **Settings → Agents** (preferred), or via env for the boot default:

```bash
# Multi-agent graph, no checkpointer (no durable gates; works without a DB):
PERSONALAI_AGENT_MODE=multi make run-backend

# Graph + Postgres: the egress-approval gate is armed automatically (no flag needed);
# add PERSONALAI_AGENT_HUMAN_GATE=true to also arm the answer-approval gate:
PERSONALAI_AGENT_MODE=multi PERSONALAI_AGENT_HUMAN_GATE=true make run-backend
```

`agent_mode` defaults to **single** and the **answer**-approval gate to **off**. The
**egress**-approval gate has no flag — it is armed whenever the graph runs with a checkpointer
(a reachable Postgres). The legacy `PERSONALAI_AGENT_GRAPH_ENABLED=true` still maps to `multi` for
backward compatibility. See [backend API](../reference/backend-api.md) for the exact SSE frames and
the resume endpoint, [ADR-0012](../architecture/adr/0012-langgraph-orchestration.md) for the
orchestration design, and [ADR-0013](../architecture/adr/0013-egress-approval-gate.md) for the
egress gate.

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
| `PERSONALAI_AGENT_VERIFIER_CHECK` | true | arm the [judge fact-check](#judge-fact-check) (a bounded independent RAG/KAG/memory lookup + a verify-only tool pass) |

## Verify against a real model

```bash
PERSONALAI_OLLAMA_IT=1 uv run pytest apps/backend/tests/test_agent_integration.py -q
```
(Opt-in; skipped in CI. Needs a local Ollama with a `tools`-capable model, e.g. qwen3.)

## Verification ladder (M8.2)

The **accuracy mode** (`PERSONALAI_AGENT_ACCURACY_MODE`, or the per-tenant `agent_accuracy_mode`
setting) controls how deeply the multi-agent graph verifies an answer:

- **`standard`** (default) — planner → researcher → critic → finalize, with the bounded reflection
  loop. Fast: no extra model call.
- **`accurate`** — adds an **LLM-judge verifier** after the critic. It returns a schema-validated
  `Verdict` (`pass` / `needs_revision` / `fail`, via the bounded, fail-closed `generate_structured`
  primitive) and, on a non-`pass` verdict, routes **one more** researcher pass (sharing the same
  bounded attempt cap as the reflection loop) before finalizing. The verdict streams to the
  reasoning pane as the **Verify** step (rose identity; verdict word green/red).

**Security gates are never accuracy-gated**: both durable gates — the answer-approval gate and the
[egress-approval gate](#2-egress-approval-gate-blocking) — always run regardless of the verification
depth.

### Judge fact-check

Independently of the accuracy mode, the multi-agent graph fact-checks the final answer against
**fresh, independently-gathered** ground truth — not just the researcher's own evidence. The judge
runs two bounded, independent checks and judges the draft against what they find:

1. a **retrieval lookup** — one re-query of the wired RAG / KAG / memory sources; and
2. a **verify-only tool pass** — a tiny (`VERIFIER_TOOL_ITERS`-bounded) run with the *researcher's
   tools* (web / MCP / etc.), prompted to confirm or refute the draft's specific claims, **not** to
   re-research. This is what lets the otherwise tool-free judge check **tool/web-derived** answers,
   not only source-grounded ones.

Each half is independently **fail-open** and may return nothing (no sources wired → no lookup; no
tools available → no tool pass). Exactly one *judge* runs the checks per turn: the **verifier** in
accurate mode (it is the last judge), and the **critic** in standard mode (when it is the last
judge), so there is never a redundant second pass.

It is controlled by `agent_verifier_check` (env `PERSONALAI_AGENT_VERIFIER_CHECK`, per-tenant in
Settings → Agents), **on by default**. The lookup is **fail-open**: any retrieval error falls back to
judging against the researcher's evidence, so it never blocks finalizing.

## What's next

Third-party **MCP servers** (M7) plug into the same gateway as additional tool sources — sandboxed
(ADR-0007) — so "ask it to search / browse / act" extends to the whole MCP ecosystem in either
runtime.
