# 3. Structured-output-first communication

- Status: Accepted
- Date: 2026-06-05

## Context

Free-text passing between models, agents, tools, and the UI is unvalidatable and unsafe,
especially when outputs trigger side effects. We need every boundary to carry validatable data.

## Decision

Make **structured outputs the primary communication format**. Use **JSON Schema** as the
canonical interchange, with **Pydantic** (Python) and **Zod** (TS) for authoring/runtime
validation. Constrain generation where supported (Ollama JSON-Schema outputs, vLLM guided
decoding). Validate at **every** boundary (model→backend, tool→backend, backend→UI). On invalid
output: bounded repair retry → deterministic repair if safe → **fail closed**. Unvalidated tool
calls are never executed. Schemas are versioned (`$id` + semver); the validator supports N/N-1.

Contracts: agent message envelope `{from, to, type, payload, schema_version}`; tool invocation
`{tool, version, args, required_permissions}`. Free text is a rendered field, not the transport.

## Consequences

- Positive: safer tool execution; renderable UI; auditable hops; localized contract changes.
- Negative: schema authoring/versioning overhead; some models need prompting + constrained
  decoding to comply.

## Alternatives considered

- Free-text + regex parsing — rejected (fragile, unsafe).
- Proprietary single-vendor function-calling only — rejected (portability/lock-in).
