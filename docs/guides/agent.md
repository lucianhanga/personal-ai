# The agent loop (M6)

With **Use tools** on, PersonalAI runs a **single-agent loop**: the model can call tools, read the
results, reason, and continue until it produces a final answer — all streamed live. Every tool call
still goes through the **gateway** (permissions, egress allowlist, schema validation, risk approval,
audit), so acting autonomously stays safe.

## What you can do

- Ask it to **act**: *"What is 23 × 19?"* → it calls the **calculator** and answers **437**.
- Ask it to **search**: *"Search the web for X and summarize"* → it calls **web_search** (egress-gated
  to DuckDuckGo) and answers with sources.
- Turn on **Reasoning** to have it think before answering; the reasoning streams and is saved.

## How it works

```
user → assemble context (RAG + memory + STM) → agent loop:
        ┌─> model.stream(tools, think)
        │      ├─ reasoning tokens  ──► live (Reasoning)
        │      ├─ answer tokens     ──► live
        │      └─ tool_calls        ──► gateway.invoke(...) ──► tool result ─┐
        └───────────────────────────────(feed result back, loop)───────────┘
        → final answer
```

- The loop **streams each model turn**, so reasoning and the answer arrive token-by-token; tool calls
  are parsed out of the stream (Ollama + OpenAI).
- Tool results are fed back as native **TOOL-role** messages so the model treats them as data.
- It stops at a final answer or a **max-iteration** guard.
- The ordered timeline (reasoning → tool call → result → …) is shown per message under **Details**
  and **persisted** (`meta.trace`), so reopening a conversation keeps it.

## Safety

- Tools run through the **gateway**: least-privilege permissions, **egress allowlist**, JSON-Schema
  I/O, **risk approval** (HIGH/CRITICAL need *approve high-risk*), timeout, and an append-only
  **audit** (the **Activity** panel, per chat).
- Tool output is **untrusted data**, never instructions.

## Configuration

| Setting | Default | Notes |
|---|---|---|
| **Use tools** (`use_tools`) | on | enable autonomous tool use |
| **approve high-risk** (`approve_tools`) | on | allow HIGH-risk tools (e.g. `http_fetch`) this turn |
| **Reasoning** (`think`) | off | ask the model to think first (slower; needs a `thinking` model) |
| egress | off | `PERSONALAI_EGRESS_ENABLED=true` + `PERSONALAI_ALLOWED_EGRESS_HOSTS=…` for network tools |
| `PERSONALAI_OLLAMA_NUM_CTX` | 32768 | bounds the context window (KV cache) |
| max iterations | 4 | safety cap on the loop |

## Verify against a real model

```bash
PERSONALAI_OLLAMA_IT=1 uv run pytest apps/backend/tests/test_agent_integration.py -q
```
(Opt-in; skipped in CI. Needs a local Ollama with a `tools`-capable model, e.g. qwen3.)

## What's next

Third-party **MCP servers** (M7) plug into this same loop and gateway as additional tool sources —
sandboxed (ADR-0007) — so "ask it to search / browse / act" extends to the whole MCP ecosystem.
