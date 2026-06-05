# Onboarding / Developer Guide

Welcome to PersonalAI. This guide gets you oriented. The project is at **Phase 0** — the
architecture is defined; application code begins at milestone **M0**.

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

## 3. Planned repository layout (from M0)

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

> This layout is created during M0. Until then the repo holds documentation only.

## 4. How we work

- **GitHub flow**, protected `main`, PRs required. See [CONTRIBUTING.md](../CONTRIBUTING.md).
- **Conventional Commits**.
- **Roadmap** milestones M0…M11. Track work on the GitHub Project board.
- **Supply chain**: every dependency is vetted and recorded in
  [SUPPLY-CHAIN.md](./supply-chain/SUPPLY-CHAIN.md). See [Dependency Policy](./policies/DEPENDENCY-POLICY.md).

## 5. Current focus: M0 — Skeleton + contracts

M0 establishes the contracts and the seams so that all later milestones are additive. See the
Project board for the M0 task breakdown.
