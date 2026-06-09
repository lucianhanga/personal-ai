# Memory: short-term + long-term (M4)

PersonalAI has two kinds of memory. Both are **local-first** (extraction + embeddings + storage run
on your machine) and the long-term one is **fully inspectable and erasable**.

| | Short-term (STM) | Long-term (LTM) |
|---|---|---|
| Scope | one conversation (isolated) | across all chats |
| Lifespan | lives with the conversation | durable, accumulates |
| Purpose | keep the thread coherent in the context window | remember facts about you |
| Mechanism | rolling summary + recent turns | extract → embed → store → recall |
| Storage | `conversations.summary` | `memories` table (pgvector) |

## Short-term memory

When a conversation grows past `PERSONALAI_STM_KEEP_RECENT` (default 10) messages, the oldest turns
are folded into a per-conversation **rolling summary**, and only the summary + the most recent turns
are sent to the model. This keeps long chats coherent without blowing the context budget. It is
**isolated per conversation** — nothing leaks between chats. Disable with
`PERSONALAI_STM_SUMMARIZE=false`.

## Long-term memory

After each turn (unless the conversation is **incognito** or `PERSONALAI_MEMORY_ENABLED=false`),
PersonalAI extracts **durable facts** from the exchange using structured output — stable facts
("works at X"), preferences ("prefers concise answers"), and notable episodes — filters by
salience, de-duplicates against what it already knows, and stores them in **pgvector** with
**provenance** (which conversation) and timestamps.

On a later turn, if **"Use my memory"** is on (`use_memory`), the most relevant memories are
retrieved and injected as a compact *"what you remember about the user"* block. Retrieved memory is
treated as **untrusted data, not instructions** (prompt-injection guardrail).

### Visualize & erase

Open the **Memory** panel in the UI to see everything remembered (with kind + provenance),
**edit** or **delete** any fact, or **Forget everything**. Over the API:

```bash
curl -H "Authorization: Bearer demo" http://127.0.0.1:8765/api/v1/memory            # list
curl -X PATCH -H "Authorization: Bearer demo" -H "Content-Type: application/json" \
     -d '{"text":"..."}' http://127.0.0.1:8765/api/v1/memory/<id>                   # edit
curl -X DELETE -H "Authorization: Bearer demo" http://127.0.0.1:8765/api/v1/memory/<id>  # delete one
curl -X DELETE -H "Authorization: Bearer demo" http://127.0.0.1:8765/api/v1/memory  # forget all
```

### Incognito chats

Start a chat with the **incognito** switch (or `POST /api/v1/conversations {"incognito":true}`) and
**nothing from it is remembered** — no long-term writes, no memory injection.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `PERSONALAI_STM_KEEP_RECENT` | `10` | recent turns kept verbatim before summarizing |
| `PERSONALAI_STM_SUMMARIZE` | `true` | enable the short-term rolling summary |
| `PERSONALAI_MEMORY_ENABLED` | `true` | extract long-term memories after a turn |
| `PERSONALAI_MEMORY_TOP_K` | `5` | memories injected when `use_memory` is on |
| `PERSONALAI_EMBED_MODEL` | `mxbai-embed-large` | embeddings for memory (1024-dim) |

## How it relates to RAG and KAG

- **RAG** (M3) answers from **documents you upload**; **memory** (M4) is about **you** and persists
  across chats. They compose — both inject reference context, both treated as data.
- **KAG** (M11) is the planned **graph upgrade** of long-term memory: extract entities + relations
  into a knowledge graph for multi-hop reasoning. Today's memory is **semantic** (vector) first.

## Full integration test (opt-in)

```bash
PERSONALAI_MEMORY_IT=1 uv run pytest apps/backend/tests/test_memory_integration.py -q
```
Real Ollama + Postgres: learns a fact from one message, then recalls it. Skipped in CI (which
covers the same paths with a Postgres service + fakes).
