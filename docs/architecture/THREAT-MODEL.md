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
