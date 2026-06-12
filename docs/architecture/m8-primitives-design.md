# M8 primitives design: durable interrupt/resume + schema-repair loop

> **Update (2026-06-12, ADR-0012):** the agent engine is now **LangGraph**, not the hand-rolled graph.
> The design below stands, with one substitution: **LangGraph's checkpoint is the durable state** and
> **replaces the hand-rolled `pending_runs` table** in §1. The security requirements are unchanged and
> become the M8.1 acceptance gate — checkpoints persist **tenant-scoped under RLS** via `TenantDb`
> (preferred: a custom `BaseCheckpointSaver`; fallback: LangGraph's Postgres saver + an app-level
> tenant guard), `thread_id = run_id`, and **cross-tenant resume must be impossible** (load only under
> the resumer's tenant; assert `tenant_id` match). Read the `pending_runs` schema below as the shape of
> the checkpoint row, not a separate hand-rolled table.

Design note for the two M8 primitives that ADR-0011 assumes but that do not exist yet (pre-M8 audit
findings A7/#233). This is a design deliverable; the code lands in M8.1 (interrupt/resume) and M8.2
(schema-repair). Built on the seams hardened in the Pre-M8 sprint: explicit `AgentContext.tenant_id`
(A2), `require_security()` (A2), the `TenantDb` unit-of-work (A3), the extended trace schema (A6).

## 1. Durable interrupt / resume (the human gate)

ADR-0011's tiered verification ends in a **human gate**: when the critic/verifier flags a turn (or a
HIGH-risk tool needs approval mid-graph), the run must **suspend**, surface an approval request to the
UI, and **resume** on a second user action. Today's approval is pre-emptive and single-shot
(`ChatRequest.approve_tools` sent up front, one POST → one SSE stream → done); there is no way to
suspend a run mid-graph and continue later.

### Chosen shape: two-phase, durable
Persist suspended state so a run survives disconnect/restart (matches ADR-0011 "durable interrupt").

1. **Suspend.** A node raises/returns an `Interrupt(reason, payload)`. The orchestrator persists the
   run to a new tenant-scoped table and closes the stream with an `approval_request` SSE event:
   ```
   pending_runs(
     id uuid pk, tenant_id uuid not null, subject_id uuid not null, conversation_id text not null,
     state jsonb not null,          -- the serialized AgentState (typed) at the interrupt point
     reason text not null,          -- e.g. "high_risk_tool" | "verification_failed"
     payload jsonb,                 -- what the user is approving (tool call, critique, ...)
     created_at timestamptz, expires_at timestamptz
   )  -- RLS: ENABLE+FORCE, tenant_isolation policy on app.tenant_id (like every domain table)
   ```
2. **Approve/Reject (resume).** `POST /api/v1/chat/{run_id}/resume {decision, csrf}` reopens an SSE
   stream. The handler:
   - resolves a **fresh** `SecurityContext` (it's a new request) via `require_context`;
   - loads the `pending_runs` row **under the resumer's tenant** (RLS) — a row owned by another
     tenant is simply not found → 404. **This is the critical isolation rule: a cross-tenant resume
     must be impossible.** Belt-and-suspenders: assert `row.tenant_id == ctx.tenant_id`.
   - rehydrates `AgentState` + an `AgentContext(tenant_id=ctx.tenant_id, …)`, applies the decision,
     continues the graph from the interrupt node, deletes the `pending_runs` row on completion.
3. **UI.** The `approval_request` event renders an approve/reject affordance (reusing the existing
   HIGH-risk approval UX); on click it calls `/resume`. The trace records a `verification`/approval
   step (A6 trace kinds).

### Why not keep one long-lived SSE + a side-channel approve
A side-channel POST signalling an `asyncio.Event` the suspended run awaits is simpler but **loses the
run on disconnect/restart** and pins a worker for the human's think-time. The durable table is the
ADR-aligned choice; the in-memory variant is an acceptable later optimization for snappy same-session
approvals, never the source of truth.

### Risks
- **Cross-tenant resume** (highest): mitigated by RLS-scoped load + explicit tenant assertion + a
  required cross-tenant resume test.
- **Replay / double-resume**: delete-on-complete + a status column; a resumed/expired run 409s.
- **Expiry/GC**: `expires_at` + a sweep; expired runs are dropped, not auto-approved (fail-closed).

## 2. Bounded schema-repair loop (verification Tier-0)

The verification ladder's Tier-0 is "schema → repair → fail-closed". The envelope exists
(`contracts/.../schemas/outputs.py: RepairRequest`, with a 1-based bounded `attempt`) but **nothing
consumes it**; nothing validates a structured generation and re-prompts on failure.

### Chosen shape: pure, bounded, fail-closed (in `personalai_core`)
A helper over `ModelProvider` + jsonschema (fully fakeable; reusable beyond M8 — memory extraction,
classification):

```
async def generate_structured(provider, request, schema, *, max_attempts=2) -> StructuredResult:
    for attempt in 1..max_attempts:
        text = await provider.generate(request_with_json_schema(schema))   # Ollama format= / OpenAI
        ok, errors = validate(text, schema)
        if ok: return StructuredResult(ok=True, data=parsed)
        request = append_repair_prompt(request, RepairRequest(attempt, errors))  # show the violations
    return StructuredResult(ok=False, error="schema validation failed after N attempts")  # fail-closed
```
- **Attempt cap small (1–2)**; never loop unbounded.
- **Fail-closed**: on exhaustion return `StructuredResult(ok=False)` — never emit unvalidated data as
  if structured.
- **Tenant/security**: it makes no DB writes itself; callers that persist results do so through the
  tenant-bound stores / unit-of-work.
- **Not a security control**: the critic/judge shares the worker's prompt-injection exposure (per the
  threat model); schema-repair is a *correctness* gate, not a trust boundary.

## 3. Sequencing
- **M8.0** — typed graph scaffolding behind `agent_graph_enabled`; single-agent loop unchanged.
- **M8.1** — interrupt/resume (`pending_runs` migration + `/resume` endpoint + UI), with the
  cross-tenant resume test as an acceptance gate.
- **M8.2** — `generate_structured` repair loop; wire Tier-0 of the verification ladder.

These close architect audit findings High #1 and High #2.
