# Security Policy

PersonalAI is **security-first**. The system assumes that prompts, files, model outputs, tool
results, and MCP servers may be malicious, and is architected around that assumption.

## Supported versions

The project is in **Phase 0 (architecture)**. No released versions yet. This policy describes
the intended posture and the reporting process.

## Reporting a vulnerability

- **Do not** open a public issue for security vulnerabilities.
- Report privately via **GitHub Security Advisories** ("Report a vulnerability" on the repo's
  Security tab) or by emailing the maintainer.
- Please include: affected component, reproduction steps, impact, and any suggested fix.
- We aim to acknowledge within a few business days and to coordinate disclosure.

## Security posture (summary)

The full design lives in
[`docs/architecture/THREAT-MODEL.md`](./docs/architecture/THREAT-MODEL.md) and
[the architecture report](./docs/architecture/PersonalAI-Architecture-Research.md#12-security-architecture).

Key controls:

| Area | Control |
|---|---|
| Network | Loopback-by-default; LAN/remote opt-in with auth; **per-tool egress allowlist**. |
| Tools / MCP | Single Tool/MCP gateway; deny-by-default permissions; tiered sandboxing; verification workflow. |
| Prompt injection | Treat retrieved/file/web content as data, not instructions; validated tool-calls; human approval for high-risk actions. |
| Files | Sandboxed parsing; strip active content; type/size limits. |
| Secrets | OS keychain / vault; never in prompts or logs; redaction in audit. |
| Supply chain | Pinned + hashed deps; SBOM; vuln scanning; signed releases. See [Dependency Policy](./docs/policies/DEPENDENCY-POLICY.md). |
| Audit | Append-only log of tool calls, approvals, egress, model routing. |
| Data privacy | Local-by-default; explicit, logged, per-provider egress; full export/delete. |

## Responsible use

PersonalAI executes tools and can connect to external services only when the user explicitly
configures and approves them. Operators are responsible for the tools and providers they enable.
