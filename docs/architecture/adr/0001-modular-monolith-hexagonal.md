# 1. Modular monolith with hexagonal (ports & adapters) architecture

- Status: Accepted
- Date: 2026-06-05

## Context

PersonalAI targets a single-user/single-host deployment but must grow many capabilities
(providers, tools, retrieval strategies, modalities, agents) over time, ideally without
rewriting the core each time. Microservices would add operational cost (inter-service auth,
deployment, mesh) without buying the isolation that actually matters here — which is tool
sandboxing and model-runtime separation (already separate processes by design).

## Decision

Build the backend as a **modular monolith** using **hexagonal architecture (ports & adapters)
plus registries**. The core depends only on interfaces in `/contracts`; concrete
implementations are adapters discovered via registries. Dependencies point inward; adapters do
not import each other; the core never imports a concrete adapter.

**Golden rule:** new capability = new adapter behind an existing port + a registry entry + a
schema. The core stays stable.

## Consequences

- Positive: changes stay local and additive; agents/humans can work in one package; easy to test
  with fake adapters; clear seams for extension.
- Negative: up-front cost at M0 to define contracts; discipline required to keep module
  boundaries from eroding.
- Dangerous parts (tools/MCP, model runtimes) remain separate processes regardless of packaging.

## Alternatives considered

- Microservices from day one — rejected (operational overhead, premature for single-host).
- Unstructured monolith — rejected (would force sweeping edits per feature).
