# 13. A blocking durable egress-approval gate for agent tool calls

- Status: Accepted
- Date: 2026-06-24
- Relates to: ADR-0012 (LangGraph orchestration), ADR-0010 (IAM / multi-tenancy), ADR-0004 (Tool/MCP
  gateway), the egress allowlist + per-call SSRF guard

## Context

PersonalAI is egress fail-closed: outbound calls are denied unless the target host is on the tenant's
allowlist, and a per-call SSRF guard additionally refuses non-public addresses (loopback, RFC1918,
link-local/metadata). Until now, when a researcher tool tried to reach a **non-allowlisted host**,
the gateway returned a tool **error** and the agent loop simply **continued without that result** —
the model kept going as if the call had failed for any ordinary reason.

That after-the-fact, silent behavior was insufficient for the multi-agent graph:

- The user never got to **decide**. A research task that genuinely needs one external host (a docs
  site, an API the user trusts) silently degraded to a worse answer with no signal that egress was
  the cause.
- The only way to permit the host was to leave the chat, open **Settings → Network**, add the host,
  and re-ask — losing the in-flight turn and its context.
- A blocked call was indistinguishable from a real failure in the trace, so the failure mode was
  invisible.

We already had the durable primitives for an in-the-loop decision: ADR-0012 adopted LangGraph and
shipped a tenant-scoped checkpointer (`TenantCheckpointSaver`) and a durable answer-approval gate
(`interrupt()`/resume). The natural fix is a **second** durable gate that turns a blocked outbound
call into an explicit, blocking decision — reusing the exact same machinery.

## Decision

Add a **second durable human-in-the-loop gate**: the **egress-approval gate**. When a researcher
tool's outbound call targets a host that is not on the tenant's allowlist, the run **pauses durably**
and asks the user what to do, before the call is allowed to proceed.

### Mechanism (engine-agnostic loop, graph fires the interrupt)

- The single-agent loop stays engine-agnostic: on a blocked outbound call it yields an
  `egress_blocked` event (carrying the tool, args, and the parsed `blocked_host`) and **returns** —
  it does **not** re-prompt the model.
- The graph routes to a new `egress_gate` node, which calls LangGraph `interrupt()` to pause. The
  run state is persisted in the **tenant-scoped checkpoint** (RLS), so it survives restarts and
  stays tenant-isolated — identical to the answer gate.
- The backend emits an `approval_request` SSE frame
  (`{run_id, reason:"egress_approval", blocked_host, tool, args}`, payload whitelisted to those
  client-facing keys) and the stream ends without a `done` frame.

### Four decisions

The user resumes via `POST /api/v1/chat/{run_id}/resume` with one verb in the body
(`{decision, conversation_id?, provider?}`):

- **Allow once** (`egress_allow_once`) — permit the blocked host for **this run only**, on a
  non-persisted config copy.
- **Allow always** (`egress_allow_always`) — **persist** the host to the **tenant** egress allowlist
  (tenant-scoped + audited) and enable egress, then resume.
- **Don't allow** (`egress_deny`) — resume with the denial; the blocked call returns its egress error
  to the agent and the turn continues without it.
- **More info** — reveal the **redacted** outbound args (secret-looking keys are deep-redacted) so
  the user can judge the request before deciding.

### Retry without duplication

On an allow, the graph re-enters the loop from a checkpointed **resume frame** that carries the
partial conversation (with the already-succeeded tool calls present as TOOL-role messages) and the
single blocked call to retry. **Only the blocked tool is retried** — prior succeeded tools are in the
conversation and **never re-fire**. The run may suspend again at a later blocked call.

### Security model

- **Host from the checkpoint, never the request body.** The resume body carries only the verb; the
  blocked host is recovered from the server-trusted checkpoint. A client cannot smuggle in an
  arbitrary destination.
- **Subject-level authz.** A run may be resumed only by the **same subject** that started it. The
  checkpoint's `subject_id` is server-trusted; a different subject — even within the same tenant —
  gets **403**. (Cross-**tenant** resume already 404s via the tenant-bound checkpointer.) Enforced on
  both gates.
- **The per-call SSRF guard survives any allow.** Allowing a host only adds it to the allowlist set;
  the tool's public-host check still runs and still refuses loopback, RFC1918, and
  link-local/metadata (`169.254.169.254`) addresses. "Allow always" on a metadata IP is still blocked
  at fetch time.
- **The allowlist write happens in the backend**, tenant-scoped and audited. No graph node touches
  the database — the `egress_gate` node only calls `interrupt()`. This preserves the ADR-0012
  load-bearing invariant (the engine gets no privileges of its own) and ADR-0010 tenant isolation.
- **More-info disclosure is redacted.** Secret-looking arg keys (`authorization`, `token`,
  `api_key`, `password`, `cookie`, `bearer`, …) are deep-redacted before the args are shown.

## Consequences

- **Better than silent failure.** Egress is now a visible, in-the-loop decision; a research task that
  needs one trusted host can proceed without abandoning the turn, and a denied one degrades
  *explicitly*.
- **No new flag, no new endpoint.** The gate reuses the ADR-0012 checkpointer and the existing
  `/resume` endpoint (dispatched on the gate's `reason`), so it is armed whenever the graph runs with
  a checkpointer (a reachable Postgres). One resume endpoint now serves two gate namespaces.
- **"Allow always" is a persistent egress channel — by design, and mitigated.** Persisting a host to
  the tenant allowlist creates a standing outbound destination, which is a real exfiltration surface.
  It is mitigated by (a) the per-call SSRF guard, which still blocks internal/metadata addresses
  after any allow, and (b) the tenant-scoped, **audited** allowlist write, so every persisted host is
  attributable. **"Allow once"** was added precisely so a user can satisfy a one-off need **without**
  opting into that persistence.
- **Added durable surface.** A second `interrupt()` point and a second `reason` namespace add code
  and test paths; the subject-authz, host-from-checkpoint, and SSRF-survives-allow rules are covered
  by API tests (including the smuggled-host and metadata-IP cases). The resumer-must-be-owner rule
  now applies to the answer gate too.
- **Slower on a blocked host.** An egress resume re-runs the researcher (a real model call) and
  carries the turn's original `provider`, so an approved host costs one extra round-trip through the
  loop. This is intentional — the alternative is degrading silently.
