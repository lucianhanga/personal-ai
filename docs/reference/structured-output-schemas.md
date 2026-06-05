# Structured-Output Schemas Reference

PersonalAI's safety model rests on **structured outputs at every boundary**: free text is never
the transport between models, agents, tools, and the UI — a schema-validated structure is
([ADR-0003](../architecture/adr/0003-structured-output-first.md), architecture report
[§9](../architecture/PersonalAI-Architecture-Research.md#9-structured-output-architecture)).
This document describes the schema backbone **as actually implemented today (M0-3)**: the model
hierarchy, each contract and its wire shape, the versioned registry, the canonical JSON Schema
artifacts, the TS/Zod bindings, and the versioning policy.

> Status: M0-3 delivers the strict/versioned Pydantic models, the five built-in contracts, the
> schema registry, the canonical JSON Schema export + drift test, and the TS/Zod bindings aligned
> by shared fixtures. The **registries and dependency injection** that wire these into the running
> FastAPI app — model-provider structured generation, the Tool/MCP gateway, the orchestrator —
> arrive in **M0-4 and beyond**. Items marked *planned (Mx)* do not exist yet.

## Source of truth

- Python models: `contracts/src/personalai_contracts/schemas/*.py`
  (`base.py`, `messages.py`, `tools.py`, `outputs.py`, `registry.py`, `export.py`)
- Public re-exports: `contracts/src/personalai_contracts/schemas/__init__.py`
- Schema tests (round-trips, fixtures, registry, drift): `contracts/tests/test_schemas.py`
- TS/Zod bindings: `packages/contracts/src/index.ts` (package `@personalai/contracts`)
- TS fixture tests: `packages/contracts/test/schemas.test.ts`
- Canonical JSON Schema artifacts: `schemas/json/*.json`
- Shared cross-language fixtures: `schemas/fixtures/**`
- Generator: `scripts/generate_schemas.py` (run via `make schemas`)

If this document disagrees with the code, the code wins — please open a fix.

This document does **not** repeat the ports/value-object reference; the message envelope and
tool-invocation contracts here are the *schema* siblings of the `ToolHandler` /
`AgentNode` ports. See [contracts-and-ports.md](./contracts-and-ports.md) for the ports.

## Model hierarchy

Every contract derives from a small foundation in
`contracts/src/personalai_contracts/schemas/base.py`.

| Type | Role |
|---|---|
| `StrictModel` | Base for all contracts. `extra="forbid"` (unknown fields rejected), `frozen=True` (immutable), `populate_by_name=True` (accept field name or alias), `validate_assignment=True`. |
| `VersionedModel` | `StrictModel` plus a stable identity: subclasses MUST set the class vars `SCHEMA_ID` (a dotted string) and `SCHEMA_VERSION` (semver). These let the registry register and resolve versions. |
| `SemVer` / `parse_semver` | A parsed `(major, minor, patch)` tuple and a strict `major.minor.patch` parser that raises `ValueError` on anything else (no pre-release/build metadata accepted). |

### Why fail-closed

`StrictModel` is deliberately strict because these payloads can trigger side effects (a tool
call, a state transition, a rendered action). The defaults make the unsafe path the failing path:

- **Unknown fields are rejected** (`extra="forbid"`), so a malformed or adversarial payload that
  smuggles extra keys does not silently validate. A consumer never sees a field it did not expect.
- **Models are immutable** (`frozen=True`), so a validated value cannot be mutated after the
  boundary check; what was validated is what is used.
- The registry's `validate()` (below) **raises rather than returns a best-effort object** on any
  problem — unknown schema, unsupported version, or a payload that fails validation. Nothing
  downstream executes an unvalidated payload. This is the same fail-closed posture the `ToolHandler`
  port and the Tool/MCP gateway enforce ([ADR-0004](../architecture/adr/0004-tool-mcp-gateway-sandbox.md)).

## The contracts

There are five built-in versioned contracts, all at `SCHEMA_VERSION = "1.0.0"` today. The
registry registers exactly this set (`_builtin_models()` in `registry.py`).

| Contract | `SCHEMA_ID` | Module | Purpose |
|---|---|---|---|
| `AgentMessage` | `personalai.agent.message` | `messages.py` | Typed envelope between agents/backend/UI. |
| `ToolInvocation` | `personalai.tool.invocation` | `tools.py` | Validated request to call a tool. |
| `ToolManifest` | `personalai.tool.manifest` | `tools.py` | A tool/MCP server's self-declaration. |
| `StructuredResult` | `personalai.output.result` | `outputs.py` | Normalized success/failure envelope. |
| `RepairRequest` | `personalai.output.repair_request` | `outputs.py` | Bounded repair retry of an invalid payload. |

Every versioned contract also carries a `schema_version` field defaulting to its `SCHEMA_VERSION`,
so a payload on the wire records the version it was produced under
([§9](../architecture/PersonalAI-Architecture-Research.md#9-structured-output-architecture)).

### AgentMessage

The typed envelope that flows between agents, the backend, and the UI. Agents never pass free-form
text to each other; `payload` is itself a schema-validated structure (free text, when present, is
one field inside it). The wire shape is `{from, to, type, payload, schema_version}`.

| Field | Wire key | Type | Required | Notes |
|---|---|---|---|---|
| `id` | `id` | `str` | no | Defaults to a generated UUID4. |
| `from_` | `from` | `str` | yes | Sender id. Exposed via the alias `from` since `from` is a Python keyword. |
| `to` | `to` | `str` | yes | Recipient id. |
| `type` | `type` | `str` | yes | Message-type discriminator (e.g. `"plan"`, `"tool_call"`). |
| `payload` | `payload` | `Mapping[str, Any]` | no | Schema-validated structured body; defaults to `{}`. |
| `schema_version` | `schema_version` | `str` | no | Defaults to `"1.0.0"`. |

Because of the `from` alias, always dump and load **by alias** (`model_dump(by_alias=True)`); the
JSON Schema is exported `by_alias=True`, so the canonical wire key is `from`, not `from_`.

```json
{ "from": "planner", "to": "researcher", "type": "plan", "payload": { "goal": "summarize" } }
```

### ToolInvocation

The validated request an agent emits to call a tool. It is checked and authorized by the Tool/MCP
gateway before any execution (M4); it mirrors the `ToolCall` value object on the `ToolHandler` port
(see [contracts-and-ports.md](./contracts-and-ports.md#toolhandler)).

| Field | Type | Required | Notes |
|---|---|---|---|
| `tool` | `str` | yes | Tool id, e.g. `"web.fetch"`. |
| `version` | `str` | yes | Tool version requested. |
| `args` | `Mapping[str, Any]` | no | Tool arguments; defaults to `{}`. |
| `required_permissions` | `Sequence[Permission]` | no | Least-privilege grants the call needs; defaults to empty. |
| `schema_version` | `str` | no | Defaults to `"1.0.0"`. |

```json
{
  "tool": "fs.read",
  "version": "1.0.0",
  "args": { "path": "/w/x.txt" },
  "required_permissions": [{ "type": "filesystem", "scope": "/w/*" }]
}
```

A `Permission` is `{type, scope}` where `type` is one of the `PermissionType` enum
(`filesystem`, `network`, `exec`, `env`, `clipboard`) and `scope` describes what the grant applies
to (a path glob, host, var name, ...). An unknown permission type fails closed.

### ToolManifest

What every tool/MCP server must declare about itself before it can be enabled. The gateway uses
this to verify provenance and enforce least privilege and egress
([ADR-0004](../architecture/adr/0004-tool-mcp-gateway-sandbox.md)).

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `name` | `str` | yes | — | Tool/server name. |
| `version` | `str` | yes | — | Tool version. |
| `provenance` | `Provenance` | yes | — | `{maintainer, repository?, license?}` — who made it / where it comes from. |
| `capabilities` | `Sequence[str]` | no | `()` | Declared capabilities. |
| `permissions` | `Sequence[Permission]` | no | `()` | Least-privilege grants; **empty means no special access**. |
| `inputs` | `Mapping[str, Any]` | no | `{}` | JSON Schema of inputs. |
| `outputs` | `Mapping[str, Any]` | no | `{}` | JSON Schema of outputs. |
| `egress` | `Sequence[str]` | no | `()` | Allowed network hosts; **empty means no egress (deny by default)**. |
| `risk` | `RiskLevel` | no | `HIGH` | One of `low`/`medium`/`high`/`critical`. **Unverified tools default to `HIGH`.** |
| `integrity` | `Integrity \| None` | no | `null` | `{algorithm, value}` (e.g. `sha256`) used to pin the tool to an exact artifact. |
| `schema_version` | `str` | no | `"1.0.0"` | |

The security-relevant defaults are intentional and verified by the tests
(`test_tool_invocation_and_manifest_round_trip`): a manifest with no explicit `risk` is `HIGH`,
and a manifest with no explicit `egress` permits **no** outbound hosts. A tool must opt *into*
trust and network access, never out of it.

```json
{
  "name": "web.fetch",
  "version": "1.0.0",
  "provenance": { "maintainer": "personalai", "repository": "https://example/repo", "license": "Apache-2.0" },
  "capabilities": ["http.get"],
  "permissions": [{ "type": "network", "scope": "example.com" }],
  "egress": ["example.com"],
  "risk": "medium",
  "integrity": { "algorithm": "sha256", "value": "<digest>" }
}
```

### StructuredResult

The normalized success/failure envelope every model/tool output is reduced to at a boundary.

| Field | Type | Required | Notes |
|---|---|---|---|
| `ok` | `bool` | yes | Success flag. |
| `data` | `Mapping[str, Any] \| None` | no | The success payload (when `ok`). |
| `error` | `ErrorInfo \| None` | no | The failure detail (when not `ok`). |
| `schema_version` | `str` | no | Defaults to `"1.0.0"`. |

**Consistency rule** (enforced by an after-validator, not just convention): an `ok=true` result
must **not** carry an `error`, and an `ok=false` result **must** carry one. Violations raise and
fail closed. `ErrorInfo` is `{code, message, details?}`.

```json
{ "ok": true, "data": { "answer": 42 } }
```

```json
{ "ok": false, "error": { "code": "E_TOOL", "message": "denied" } }
```

### RepairRequest

The structured input to a **bounded** repair retry. When a payload fails validation, a
`RepairRequest` carries the invalid payload and the validation errors back to the producer to
re-ask with the schema and errors. If repair still fails, the system fails closed — the consumer
never executes an unvalidated payload ([ADR-0003](../architecture/adr/0003-structured-output-first.md)).

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_id` | `str` | yes | The contract that was violated. |
| `target_version` | `str` | yes | Version the payload should validate against. |
| `invalid_payload` | `Mapping[str, Any]` | yes | The payload that failed. |
| `errors` | `Sequence[str]` | yes | Human/model-readable validation errors. |
| `attempt` | `int` (>= 1) | yes | 1-based attempt counter; the **bound is enforced by the caller**, not the schema. |
| `schema_version` | `str` | no | Defaults to `"1.0.0"`. |

```json
{
  "schema_id": "personalai.output.result",
  "target_version": "1.0.0",
  "invalid_payload": { "ok": true, "error": { "code": "E", "message": "x" } },
  "errors": ["ok result must not carry an error"],
  "attempt": 1
}
```

> Note: the repair *loop* (re-ask, deterministic repair, give-up bound) is a consumer concern that
> lands with the structured-generation wiring (M0-4+). M0-3 ships only the `RepairRequest`
> contract, not a runner that drives it.

## The schema registry

`contracts/src/personalai_contracts/schemas/registry.py` holds the `SchemaRegistry`, the
fail-closed `validate()` entry point, and the two error types. `default_registry()` returns a
registry pre-populated with all five built-in contracts.

```python
from personalai_contracts.schemas import default_registry, SchemaError, SchemaValidationError

registry = default_registry()
msg = registry.validate("personalai.agent.message", "1.0.0", {"from": "a", "to": "b", "type": "ping"})
```

### Registration

`register(model)` stores a `VersionedModel` subclass keyed by `SCHEMA_ID` then `SCHEMA_VERSION`,
after parsing the version to fail fast on a malformed semver. Multiple versions of the same
`SCHEMA_ID` coexist in the registry.

### N and N-1 major-version support

The registry serves the **current major (N) and the previous major (N-1)** for a given schema id:

- `supported_majors(schema_id)` returns the top two distinct registered majors, highest first.
- `is_supported(schema_id, version)` is true only when the exact version is registered **and** its
  major is in the supported set. So with `1.0.0`, `2.0.0`, `3.0.0` registered, `3.0.0` and `2.0.0`
  are supported but `1.0.0` (N-2) is not — and an unregistered version like `5.0.0` is not either.
  This is exactly what `test_registry_supports_n_and_n_minus_1` asserts.

### Fail-closed validate()

`validate(schema_id, version, payload)` is the single boundary entry point. It fails closed on
every problem:

| Condition | Raises |
|---|---|
| `schema_id` not registered at all | `SchemaError` (`unknown schema id`) |
| version not registered, or major outside N / N-1 | `SchemaError` (`unsupported version`) |
| payload does not validate against the model | `SchemaValidationError` (carries `schema_id`, `version`, and the list of error strings) |
| payload validates | returns the frozen `VersionedModel` instance |

`SchemaError` means "I will not even try this schema/version"; `SchemaValidationError` means "I
tried and the data is wrong." Consumers that want to attempt a repair catch `SchemaValidationError`
and build a `RepairRequest` from its `.errors`; an unknown schema/version is not repairable.

## Canonical JSON Schema

JSON Schema is the canonical interchange format ([ADR-0003](../architecture/adr/0003-structured-output-first.md)).
The committed artifacts live at the repo root under `schemas/json/`, one file per contract named
`<schema_id>-<version>.json`:

- `personalai.agent.message-1.0.0.json`
- `personalai.tool.invocation-1.0.0.json`
- `personalai.tool.manifest-1.0.0.json`
- `personalai.output.result-1.0.0.json`
- `personalai.output.repair_request-1.0.0.json`

### How it is generated

`schemas/export.py` produces them from the Pydantic models via `model_json_schema(by_alias=True)`
(so e.g. `AgentMessage` exports the `from` key), rendered deterministically with
`json.dumps(..., indent=2, sort_keys=True)` plus a trailing newline for stable diffs. The
generator script writes them:

```bash
make schemas        # -> uv run python scripts/generate_schemas.py
```

After changing any model, regenerate and commit the result.

### The drift test

`test_committed_json_schema_matches_models` in `contracts/tests/test_schemas.py` re-renders each
schema from the live models and asserts it byte-for-byte equals the committed file. If they differ,
the test fails with: *"... is stale - run `make schemas` and commit the result."* CI runs this, so
the committed JSON Schema can never silently drift from the Python models.

## TS/Zod bindings

`packages/contracts` (package `@personalai/contracts`) provides Zod bindings that mirror the Python
models and are aligned against the canonical JSON Schema. `packages/contracts/src/index.ts`
currently exports `AgentMessageSchema`, `ToolInvocationSchema`, `PermissionSchema`,
`ErrorInfoSchema`, and `StructuredResultSchema` (plus their inferred TS types). Every object schema
is `.strict()` — the Zod equivalent of `extra="forbid"`, so unknown keys are rejected on the TS
side too. `StructuredResultSchema` re-implements the ok/error consistency rule with a
`superRefine`, matching the Python after-validator.

> Drift to note (see below): `ToolManifestSchema` and `RepairRequestSchema` are **not** yet exported
> on the TS side. The shared-fixture test only covers the three contracts that have fixtures.

### Shared fixtures keep Python and TS aligned

Both languages exercise the **same** payloads in `schemas/fixtures/`, organized as
`<contract>/valid/*.json` and `<contract>/invalid/*.json`:

```
schemas/fixtures/
  agent-message/      valid/{basic,minimal}.json        invalid/{extra-field,missing-to}.json
  tool-invocation/    valid/{basic,with-permissions}.json  invalid/{bad-permission,missing-version}.json
  structured-result/  valid/{ok,error}.json             invalid/{ok-with-error,failed-without-error}.json
```

- Python: `test_valid_fixtures_pass` validates every `valid/*.json` through `default_registry()`;
  `test_invalid_fixtures_fail_closed` asserts every `invalid/*.json` raises `SchemaValidationError`.
- TS: `packages/contracts/test/schemas.test.ts` loads the same files and asserts `safeParse`
  succeeds on `valid/*` and fails on `invalid/*`.

Because a fixture must pass (or fail) **identically in both bindings**, the Python and TS contracts
cannot silently diverge on the shapes that have fixtures. The invalid fixtures are deliberately
chosen to exercise the fail-closed rules: an extra field, a missing required field, an unknown
permission type, and both halves of the StructuredResult consistency rule.

### Running the bindings

```bash
make js-test        # vitest run across the pnpm workspace (includes the fixture suite)
make js-typecheck   # tsc --noEmit
```

See [toolchain.md](../development/toolchain.md) for the full workspace setup.

## Versioning policy

Schemas are versioned with `$id` + semver and consumers validate at **every** boundary
([ADR-0003](../architecture/adr/0003-structured-output-first.md), coding standards
[§2](../development/coding-standards.md#2-structured-output-first)). To evolve a contract:

1. **Decide the bump.** A breaking change (removed/renamed/retyped required field, or a tightened
   rule) is a **major** bump; additive optional fields are minor; doc/format-only changes are patch.
2. **Add the new versioned model.** Create a new `VersionedModel` (or bump `SCHEMA_VERSION` on the
   existing one) and register it. Keep the previous major registered so the registry can serve N
   and N-1 — do not delete the old version when you ship the new one.
3. **Regenerate artifacts.** Run `make schemas` and commit the new `schemas/json/*.json` file(s);
   the drift test will otherwise fail.
4. **Mirror the TS binding** in `packages/contracts/src/index.ts` and add shared fixtures under
   `schemas/fixtures/<contract>/` so both bindings are exercised against the new shape.
5. **Migrate consumers deliberately.** Producers emit `schema_version`; consumers validate at the
   boundary and accept N and N-1. Bump a consumer to the new major only when it is ready; once all
   consumers are off the oldest major, that version can be retired (it then falls outside N / N-1).

The golden rule applies: a new capability is a new adapter behind an existing port **plus a
schema** — adding or evolving a schema is the normal, contained way the system grows
(architecture report [§22](../architecture/PersonalAI-Architecture-Research.md#22-modular-implementation-roadmap)).

## Common mistakes

- Dumping `AgentMessage` without `by_alias=True` and getting `from_` instead of the wire key
  `from`. Always round-trip by alias; the JSON Schema is exported by alias.
- Expecting `validate()` to return `None` or a partial object on bad input — it raises. Catch
  `SchemaValidationError` (repairable) vs `SchemaError` (unknown/unsupported — not repairable).
- Editing a model and forgetting `make schemas`; the drift test then fails in CI.
- Treating an empty `egress` or unset `risk` on a `ToolManifest` as "no opinion" — they mean
  "deny egress" and "HIGH risk" respectively.
- Assuming the repair loop exists. M0-3 ships the `RepairRequest` *contract*; the runner is later.

## Related

- [ADR-0003 — structured-output-first](../architecture/adr/0003-structured-output-first.md)
- [ADR-0004 — tool/MCP gateway + sandbox](../architecture/adr/0004-tool-mcp-gateway-sandbox.md)
- [Contracts & ports reference](./contracts-and-ports.md) — the M0-2 ports these schemas pair with.
- [Coding standards & conventions](../development/coding-standards.md) — structured-output-first rules.
- [Toolchain & monorepo](../development/toolchain.md) — `make schemas`, `make js-test`, CI jobs.
- [Architecture report §9 — structured output architecture](../architecture/PersonalAI-Architecture-Research.md#9-structured-output-architecture)
- [Architecture report §22 — modular implementation roadmap](../architecture/PersonalAI-Architecture-Research.md#22-modular-implementation-roadmap)

## Last updated notes

- 2026-06-05: Initial reference for the M0-3 schema backbone (strict/versioned models, five
  built-in contracts, registry, JSON Schema export + drift test, TS/Zod bindings, shared fixtures).
  Registries/DI that consume these (structured generation, gateway, orchestrator) are M0-4+ and
  referenced as upcoming, not documented as existing. Known binding gap: `ToolManifest` and
  `RepairRequest` are not yet exported as Zod schemas.
</content>
</invoke>
