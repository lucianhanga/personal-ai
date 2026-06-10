# 10. Identity, authentication & multi-tenancy (always-on, RLS-isolated)

- Status: Accepted
- Date: 2026-06-10
- Revises: ADR-0002 (local-first) — local-first remains, but the app is now **always authenticated +
  multi-tenant**, even for local/personal use.

## Context

PersonalAI must serve three scenarios from **one codebase**: (1) local dev/test on a Mac, (2) the
author's personal use, and (3) a cloud-agnostic, multi-tenant SaaS running in an isolated VM (today
a single co-located Postgres; later docker-compose/k8s with each component containerized). The
current posture (loopback, single-user, bearer token, "operator == user") does not cover (3), and
bolting tenancy on later is risky. Decision: make **multi-tenancy and authentication always on** so
the production isolation path is exercised continuously — locally the developer is simply tenant #1.

## Decision

### Spine — a fail-closed `SecurityContext`
Every request resolves a **request-scoped, fail-closed `SecurityContext{subject_id, tenant_id}`**
that flows through all ports, repositories, the audit log, the agent loop, and the Tool/MCP gateway.
**No tenant context ⇒ deny.** Isolation is enforced by **two independent layers** — an app-layer
tenant filter **and** Postgres Row-Level Security — neither permitted to be the sole control
(defense in depth).

### Tenancy model
Real `tenants` + `users` + `memberships` tables from day one (not `tenant_id == user_id`). MVP =
one user per tenant (personal use = a 1-member tenant); organizations/teams become an **additive**
membership layer later, not a rewrite.

### Authentication — `IdentityProvider` port
Auth is a hexagonal seam (like `ModelProvider`):
- **Built-in adapter (now):** argon2id passwords **+ WebAuthn passkeys**, email verify/reset.
  Self-contained — runs in the single process, no external IdP required.
- **OIDC adapter (post-MVP):** standard OIDC for hosted SaaS/enterprise SSO (Keycloak/Entra/Auth0),
  drop-in via the same port.
- **Dev-login** convenience (seeded tenant + gated auto-login) that is **never** built into hosted
  artifacts.

### Sessions & tokens
- Browser SPA: **opaque server-side sessions** (stored in Postgres, tenant-scoped, **revocable**)
  delivered in a `__Host-` cookie (`Secure`, `HttpOnly`, `SameSite=Strict`), with **CSRF** tokens.
  This supersedes the local `sessionStorage` bearer token (#139) for hosted mode.
- Programmatic/local clients: **bearer API keys** issued through the same identity layer.
- Sliding idle (~24h) + absolute (~7d) timeouts, server-side revocation; configurable.

### Tenant isolation in Postgres (RLS)
`ENABLE` + `FORCE` RLS with `USING` + `WITH CHECK` on every domain table; policy keyed on
`current_setting('app.tenant_id')` (errors if unset ⇒ fail-closed); `tenant_id` as the leading
index column. A single `TenantDb.acquire(tenant_id)` binds the tenant **per-transaction**
(`set_config(..., is_local=true)`, never SESSION — asyncpg pool reuse would leak), and every
repository receives an already-bound connection, so a forgotten tenant filter is structurally
impossible. Two roles: `personalai_app` (`NOBYPASSRLS`) at request time, `personalai_admin`
(`BYPASSRLS`) for migrations/system jobs. **pgvector ≥ 0.8** with `hnsw.iterative_scan` (ANN ranks
by distance before RLS filters — without it small tenants suffer recall collapse);
partition-by-tenant is the scale escape hatch and on-ramp to DB-per-tenant.

### Per-tenant secrets — `KeyProvider` port
Per-tenant secrets (MCP env/API keys, provider keys) stored **encrypted** (envelope encryption, app
master key) in a tenant-scoped table now, behind a `KeyProvider` port so KMS/Vault drops in later.
Never cross-tenant; existing redaction/masking still applies.

### MCP / tool execution under multi-tenancy
A tenant spawning **stdio** MCP subprocesses on a shared VM is a tenant→host→all-tenants compromise.
Therefore **hosted mode = remote-HTTP MCP only**; **stdio stays local-only** (your Mac / single-user
VM). Re-enabling stdio safely in hosted mode requires the **container executor tier deferred in
ADR-0009** — that is the documented future path. ADR-0009's "stdio runs with user privileges" is
accepted for local-single-user only and **does not transfer to hosting**.

## Consequences

- A second, **hosted multi-tenant threat model** is added to THREAT-MODEL.md (cross-tenant access /
  IDOR / RLS bypass / per-tenant secrets / shared-VM MCP / per-tenant egress + quotas).
- The browser auth migration (cookie sessions + CSRF) is a UI-developer task and partially reverses
  #139 (correct: bearer/sessionStorage suited the local model; cookies suit hosting).
- **Sequencing:** this milestone lands **before** the M8 multi-agent work so agent state is built
  tenant-aware from the start.
- **MVP cut:** built-in auth (password+passkey), tenants/users/memberships, RLS on all domain tables,
  server sessions + API keys, per-tenant secrets, remote-HTTP-MCP-only in hosted.
  **Deferred:** OIDC/SSO, MFA/TOTP, organizations/teams UI, billing, container MCP tier, DB-per-tenant.
- The seams (`IdentityProvider`, `KeyProvider`, `TenantDb`) keep all of this swappable without core
  changes, consistent with ADR-0001.

## Decisions made (optimizing for stability / scalability / extensibility)

Real tenant entity; password+passkey behind a port; server-side revocable cookie sessions + CSRF;
remote-HTTP-MCP-only hosted; encrypted secrets table behind `KeyProvider`; IAM before M8. See the
table in the design discussion; product knobs (timeouts, KMS choice) are config, not architecture.
