# personalai-provider-hf-reranker

In-process cross-encoder reranker for the RAG pipeline (#492). Implements the
`Reranker` port by re-scoring retrieved items against the query with a HuggingFace
cross-encoder (default `Qwen/Qwen3-Reranker-0.6B`), running in-process — no separate
server, no network egress.

## Design

- **Flag-gated, on-demand.** Nothing loads unless `PERSONALAI_RERANK_ENABLED=true`.
  The model weights load on first rerank call and are cached per process; there is no
  warm footprint when the flag is off.
- **In-process, local.** The model is downloaded once from HuggingFace (then cached and
  usable offline) and runs in a worker thread (`asyncio.to_thread`) so the event loop
  stays responsive.
- **Half precision.** `float16` inference — half the memory of `float32`, fine for
  ranking (logits are used ordinally, not as calibrated probabilities).

## Installation

The heavy ML stack (`torch`, `transformers`) is an **optional extra** so the base
workspace stays lightweight. Install it only when you want reranking:

```bash
uv sync --extra ml          # or: uv pip install "personalai-provider-hf-reranker[ml]"
```

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `PERSONALAI_RERANK_ENABLED` | `false` | Turn the rerank stage on. |
| `PERSONALAI_RERANK_MODEL` | `Qwen/Qwen3-Reranker-0.6B` | HuggingFace reranker model id. |

When enabled, the backend wires the reranker into `VectorSource`, which re-scores the
retrieved items immediately after vector retrieval and before evidence assembly.
