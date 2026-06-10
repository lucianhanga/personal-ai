# Threat Model (v1)

> Scope: high-level threat model for PersonalAI at the architecture stage. Refined per milestone.
> Companion to [§12 Security Architecture](./PersonalAI-Architecture-Research.md#12-security-architecture).

## 1. Assets

- User data: conversations, files, embeddings, long-term memory.
- Secrets: provider API keys, OAuth tokens, local credentials.
- Compute & host integrity (the user's machine/server).
- The integrity of model outputs and tool actions taken on the user's behalf.

## 2. Core assumption

**Everything crossing a boundary is untrusted:** prompts, uploaded files, web/retrieved content,
model outputs, tool results, and MCP servers (local and remote) may all be adversarial.

## 3. Trust boundaries

1. **Client ↔ Gateway** — loopback by default, authenticated, origin-checked.
2. **Core ↔ Model runtimes** — separate processes; remote egress gated.
3. **Core ↔ Tools/MCP** — the **critical** boundary; sandbox + permission + egress enforced.
4. **Host ↔ Remote** — network egress allowlist; opt-in providers only.

## 4. Threats and controls

| # | Threat | Vector | Control |
|---|---|---|---|
| T1 | Prompt injection → unintended tool use | Malicious file/web/retrieved content | Content treated as data not instructions; validated tool-calls; human approval for high-risk actions |
| T2 | Data exfiltration via tool chaining | Compromised/abused tool with network | Per-tool egress allowlist; default no network; audit outbound calls |
| T3 | Malicious document | Crafted PDF/office file exploiting parser | Sandboxed parsing; strip active content; size/type limits |
| T4 | Unsafe code execution | Tool runs untrusted code | Tiered sandbox (container → gVisor → microVM/WASM); no host-kernel trust for untrusted code |
| T5 | Insecure / malicious MCP | Third-party MCP server | Verification workflow; pin+hash; OAuth 2.1; no token passthrough |
| T6 | Over-permissive agent | Broad grants | Deny-by-default; least-privilege; per-scope enablement |
| T7 | Supply-chain / dependency confusion | Malicious package | Pin + hash; private scoping; SBOM; scanning; signed releases |
| T8 | Secret leakage | Secrets in prompts/logs | OS keychain/vault; redaction; never in prompts |
| T9 | Extension over-reach | Browser extension scraping | MV3 minimal perms; explicit user capture; authenticated localhost; audited |
| T10 | Model/provider isolation failure | Cross-provider leakage | Provider isolation; egress per provider; local-by-default |

## 5. Out of scope (v1)

- Nation-state physical attacks on the host.
- Vulnerabilities in the underlying OS/hardware.
- Multi-tenant cloud hardening (single-user/self-host is the v1 target).

## 6. Residual risks (tracked)

- Strong sandboxing (gVisor/microVM) is Linux-centric; macOS/Windows desktop isolation for
  untrusted tools is weaker and needs design attention (open question §20).
- MCP ecosystem is young and CVE-prone; verification overhead is mandatory.
- LLM-as-judge is not a security control (it shares the worker's injection exposure).

### 6.1 M0-10 baseline — known limitations (from the security review)

The M0-10 primitives are a foundation; these gaps are deliberate and tracked:

- **Egress guard is a string/host check only.** `assert_egress_allowed` fails closed by default
  and enforces a host allowlist, but does not defend against IP-literal hosts, loopback/SSRF
  tricks, DNS rebinding, or redirect-following. Robust egress enforcement belongs to the
  **Tool/MCP gateway (M5, T3 boundary)**. **Empty allowlist = deny all:** enabling egress
  (`PERSONALAI_EGRESS_ENABLED=true`) with no `PERSONALAI_ALLOWED_EGRESS_HOSTS` denies every
  non-loopback host; opening egress to any host is an explicit opt-in
  (`PERSONALAI_EGRESS_ALLOW_ANY=true`).
- **Redaction is key-name based.** Secrets embedded in free-text values or URLs under innocuous
  keys are not yet masked; value-level masking (JWT/AWS/bearer/basic-auth patterns) is deferred to
  **M1**. Callers must not place raw secrets into free-text payload fields.
- **Audit log immutability is in-process only** (open mode `a`, owner-only `0o600`, no external
  tamper-evidence). Hash-chaining / append-only OS attributes are deferred to **M1**. No
  multi-writer locking yet (single-writer assumption).
- **API CORS allowlist** (`CORSMiddleware`) restricts browser origins to the configured
  (loopback) allowlist and handles preflight; requests with no `Origin` (curl, tests) are
  unaffected. The bearer token is the real auth control (credentials/cookies are not used). A
  non-loopback bind without an auth token is refused at startup. CSRF protection beyond this is
  unnecessary while loopback-only. The web UI keeps the token in **`sessionStorage`** (cleared when
  the tab closes; migrated off `localStorage`) to shrink the XSS exfiltration window. **Rotate**
  `PERSONALAI_AUTH_TOKEN` periodically and immediately if it may have been exposed (set a new value
  in the env and re-enter it in the UI; the old token stops working at once).
- **Release signature verification** uses a repo-scoped identity regexp; tightening to the exact
  release workflow/tag is deferred to the hardening milestone (M11).

## Tool/MCP gateway (M5)

All side effects route through one **Tool gateway** (ADR-0004, ADR-0007). Enforced, fail-closed
and in order: version pinning, **risk approval** (HIGH/CRITICAL need explicit approval),
**least-privilege permissions** (deny-by-default), **JSON-Schema validation of both inputs and
outputs**, the **network egress allowlist** for declared hosts, an execution **timeout**, and an
**append-only audit** of every allowed/denied call (redacted). Tool output is **untrusted data**:
agents must treat it as data, not instructions (same guardrail as RAG/memory context).

Realized this milestone:

- **Egress for tools is enforced at the gateway and per-tool.** `http_fetch` (and `web_search`,
  which is pinned to `html.duckduckgo.com`) check the target host against the allowlist on every
  call and **disable redirects** (so a response cannot bounce to a disallowed host). The
  string/host limitations noted above (IP-literals, SSRF, DNS rebinding) still apply and are
  tightened with the subprocess/container tiers in M7. Enabling egress with an empty allowlist
  denies everything (fail-closed); see the egress note in §6.1.
- **The single-agent loop (M6) calls tools only through this gateway.** Autonomous tool use does
  not bypass any gate: risk approval, permissions, egress, schema validation, timeout, and audit
  all still apply on every call, and tool output is fed back to the model as untrusted data.

Deliberate gaps (tracked):

- **Tier-0 execution is in-process (no OS isolation)**, so only *trusted first-party* tools run
  there. Untrusted/third-party **MCP servers** must run under tier-1 (subprocess) / tier-2
  (container) isolation, which lands with MCP in **M7** (ADR-0007); the executor seam is in place.
- **Permission grants are per-request.** Remembered per-scope grants and a human-approval UI flow
  for high-risk actions are a follow-up.
