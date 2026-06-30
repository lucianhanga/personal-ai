# Onboarding / Developer Guide

Welcome to PersonalAI. This guide gets you oriented. PersonalAI is a working, local-first modular
monolith: a FastAPI backend, a React SPA + Tauri shell, stable `contracts`, and the seam packages
(providers, retrieval, storage, modalities, tools, agents) wired together through registries. This
guide explains the mental model and how to start contributing.

## 1. What this project is

A local-first, omni-capable AI assistant. Read these first, in order:

1. [README](../README.md) — the elevator pitch and current state.
2. [Architecture report](./architecture/PersonalAI-Architecture-Research.md) — the full design.
3. [Threat model](./architecture/THREAT-MODEL.md) — how we think about security.
4. [ADRs](./architecture/adr/) — the decisions and why.

## 2. Mental model (hexagonal + registries)

Everything is built around **stable contracts** in `/contracts`, with concrete implementations
plugged in as **adapters** discovered via **registries**. The golden rule:

> New capability = new adapter behind an existing port + register it + declare its schema.
> The core does not change.

The seams (extension points) you will work in:

| Seam | You add… |
|---|---|
| Model providers | a `ModelProvider` adapter |
| Tools / MCP | a manifest + sandboxed handler |
| Retrieval | a `Retriever` strategy |
| Storage | a repository adapter |
| Modalities | a `ModalityHandler` |
| Agents / roles | a graph node + typed messages |
| UI renderers | a component keyed by output type |

The ports behind these seams are defined in `personalai_contracts`. For exact signatures, value
objects, the reference fakes, and the step-by-step "how to add an adapter" workflow, see the
[Contracts & ports reference](./reference/contracts-and-ports.md). For the rules you must follow
while writing code, see [Coding standards](./development/coding-standards.md) and the
[Toolchain & monorepo](./development/toolchain.md) guide.

## 3. Repository layout

```
/contracts        # schemas, ports, message envelopes (the stable core API)
/core             # orchestration, gateway, security engine, validation
/providers/*      # ollama, llamacpp, vllm, remote-litellm
/retrieval/*      # vector-pgvector, graph-age, keyword
/storage/*        # postgres, qdrant, object-store
/modalities/*     # files-tika, files-docling, stt-whisper, tts-piper, vision
/tools/*          # internal tools + MCP adapters
/agents/*         # planner, researcher, critic, ...
/apps/backend     # FastAPI wiring (DI from registries)
/apps/ui          # Tauri + SPA
/apps/extension   # MV3 browser extension
```

> `contracts` is the stable core API; `core` holds the orchestration, gateway, and validation;
> `apps` wires everything into the backend and UI; the seam packages (`providers`, `retrieval`,
> `storage`, `modalities`, `tools`, `agents`) provide the concrete adapters.

## 4. How we work

- **GitHub flow**, protected `main`, PRs required. See [CONTRIBUTING.md](../CONTRIBUTING.md).
- **Conventional Commits**.
- **Supply chain**: every dependency is vetted and recorded in
  [SUPPLY-CHAIN.md](./supply-chain/SUPPLY-CHAIN.md). See [Dependency Policy](./policies/DEPENDENCY-POLICY.md).

## 5. Start contributing

1. **Set up** the workspace: `make setup` (uv + pnpm). See
   [Toolchain & monorepo](./development/toolchain.md).
2. **Run it locally**: `make run-backend` for the backend and `pnpm --filter @personalai/ui dev`
   for the UI — see the [Local chat guide](./guides/local-chat.md).
3. **Find the seam** your change belongs behind (the table above) and read the
   [Contracts & ports reference](./reference/contracts-and-ports.md) and
   [Dependency injection & registries](./reference/dependency-injection.md) for the
   "how to add an adapter" workflow.
4. **Follow the rules** in [Coding standards](./development/coding-standards.md) — typed under mypy
   strict, structured-output-first, inward-only dependencies (enforced by import-linter).
5. **Run the checks** before a PR: `make check` (lint + types + tests + architecture + JS).

The golden rule keeps changes contained: a new capability is a new adapter behind an existing port,
registered and schema-declared — the core stays stable.
