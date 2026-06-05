# 2. Local-first with Ollama as default runtime behind a provider abstraction

- Status: Accepted
- Date: 2026-06-05

## Context

The product must run open-source models on the user's hardware and keep data local by default,
while optionally allowing remote providers when explicitly configured. We need an easy default
local runtime and the freedom to switch runtimes/providers later.

## Decision

Default to **Ollama** for local model serving and management. Access all models through an
**OpenAI-compatible `ModelProvider` port** with capability detection (text, vision, embeddings,
tool calling, structured output, context length). **llama.cpp** and **vLLM** are alternative
local adapters; **LiteLLM** is the opt-in remote-provider adapter and egress chokepoint. Remote
egress is off by default and per-provider opt-in, and is logged.

## Consequences

- Positive: lowest-friction local default; portability across runtimes; clear privacy story.
- Negative: local models may underperform frontier cloud models; mitigated by honest capability
  badges and opt-in remote routing.
- Embedding model is pinned and versioned (changing it reindexes vectors).

## Alternatives considered

- llama.cpp as default — more control, more friction; kept as adapter.
- vLLM as default — best throughput but Linux+GPU only; kept as adapter.
- Cloud-first — rejected (violates local-first principle).
