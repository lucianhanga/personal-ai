# tools/test — NER / KAG extraction playground

Scratch harness for experimenting with the local entity extractor that feeds the knowledge graph
(KAG). Built while debugging why the Qwen3 35B MoE produced nothing on the real folder corpus (#464).

Everything runs fully local against your Ollama + the configured model. Nothing here is part of the
app or the test suite — it is for hand experiments.

## What's here

| File | What it does |
| --- | --- |
| `ner_extract.py` | Runs the windowed extractor and lets you **compare providers** — the local Ollama model vs an OpenAI model — with the same prompt + merge, and see entities + timing. |
| `ner_curl.sh` | The **raw** Ollama request one NER window makes, via `curl` — for poking at the model directly. |
| `sample_invoice.txt` | A small sample invoice to extract from. |

## Quick start

```bash
# Real code path (recommended) — sample text:
uv run python tools/test/ner_extract.py

# A file:
uv run python tools/test/ner_extract.py --file tools/test/sample_invoice.txt

# The first document already in your index (reconstructed from its chunks, no OCR):
uv run python tools/test/ner_extract.py --first-doc

# Compare the local model against OpenAI (needs OPENAI_API_KEY):
export OPENAI_API_KEY=sk-...
uv run python tools/test/ner_extract.py --provider openai --file tools/test/sample_invoice.txt
uv run python tools/test/ner_extract.py --provider both   --first-doc

# Raw model call via curl (streams live + prints timing):
bash tools/test/ner_curl.sh "Rechnung von M-Net GmbH, 39,99 EUR, R-2026-0042, 2026-01-15"
```

## Comparing models (Ollama vs OpenAI)

`--provider openai` runs the same windowed extraction through an OpenAI model (a direct API call, so
it can set `reasoning_effort`). The default is **`gpt-5-nano`**; pass `--openai-model gpt-4o-mini`
(fast non-reasoning) or `gpt-5-mini` (more capable). OpenAI has no empty-output-on-large-window
problem, so give it a bigger `--window` (fewer, cheaper calls). `--provider both` runs local + OpenAI
back to back. Each OpenAI run prints **token usage** (`in / out / reasoning`) so you can gauge cost.

**Reasoning effort.** `gpt-5-*` / o-series are reasoning models — they "think" before answering,
which is slow and bills reasoning tokens as output. `--openai-reasoning minimal` (the default) makes
them barely think, which is what you want for NER. Raise it (`low`/`medium`/`high`) only if quality
needs it. Non-reasoning models (`gpt-4o-mini`, `gpt-4.1-*`) ignore the flag.

## The knobs that actually matter (hard-won)

- **`--num-ctx` / `NUM_CTX` (default 32768).** Full context. If Ollama **OOM-crashes** loading the
  35B at 32K on your hardware (`Server disconnected` / `connection refused`), drop to `4096` — a
  small NER window needs little context anyway.
- **`--window` / text length small (~1200 chars).** This MoE returns **empty** structured output on
  large windows — a ~4000-char window comes back with zero tokens, while a 1200-char one extracts
  reliably. Reproduce the cliff:
  ```bash
  uv run python tools/test/ner_extract.py --first-doc --sweep 800,1200,2000,4000
  ```
- **`format` = the JSON schema** forces structured output (already wired in both scripts).
- **reasoning mode.** `ner_curl.sh THINK=no_think|low|off` toggles how reasoning is requested.
  `/no_think` is what reliably produces on small windows here; `low` was less stable on this box.

## Notes

- The 35B is shared with the running app — experiments compete with it, so a call can be slow if the
  app is busy.
- `ner_extract.py --first-doc` reads `vectors.metadata->>'text'`; it needs the DB reachable
  (`PERSONALAI_DATABASE_URL`, default local).
