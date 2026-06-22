# PersonalAI benchmarks (M-Bench)

A dev-only harness that benchmarks personalIA in multiple configurations and produces a
capability-tier leaderboard. It drives the backend over HTTP through the non-streaming
`POST /api/v1/assistant/execute` endpoint, so it stays decoupled from the app internals (it imports
no `personalai-*` package) and could even point at a remote deployment.

Phase 1 is **local-only** (no frontier API keys). Phase 2 adds frontier-model adapters (Claude / GPT
/ Gemini), a tool-equipped wrapper for them, and cost/latency-adjusted leaderboards.

## Run it

Start the backend (it listens on `127.0.0.1:8765` by default), then:

```bash
# from the repo root
uv run python -m personalai_benchmarks run            # all tasks x all modes -> ./benchmark-results
uv run python -m personalai_benchmarks list-modes     # show available modes
uv run python -m personalai_benchmarks run \
    --task-ids reasoning_arithmetic_order,tool_calc_large_product \
    --modes single_no_tools,single_tools_mcp \
    --base-url http://127.0.0.1:8765 --out ./benchmark-results

# Local models are stochastic — run each cell several times for pass@k + pass-rate:
uv run python -m personalai_benchmarks run --repeats 5

# Compare PersonalAI vs frontier models on quality (LLM judge). Frontier keys come from the
# environment (e.g. via uv's --env-file); providers without a key are skipped.
uv run --env-file .env python -m personalai_benchmarks compare
uv run --env-file .env python -m personalai_benchmarks compare \
    --no-personalia --providers anthropic,openai,deepseek --task-ids quality_explain_recursion

# Also run frontier models WITH tools (the assistant/"chat" variant — they call PersonalAI's tools):
uv run --env-file .env python -m personalai_benchmarks compare --frontier-tools
```

## Phase 2: frontier comparison + LLM judge

`compare` runs PersonalAI (across its modes) **and** each frontier model that has an API key (raw
tier) over the same tasks, then writes one combined leaderboard grouped by capability tier.

- **Providers** (`frontier.py`): one OpenAI-compatible adapter reaches OpenAI / Anthropic / DeepSeek
  / xAI (Grok) / Groq / Gemini. Keys come from the environment (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  `DEEPSEEK_API_KEY`, `XAI_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`); a provider without a key is
  skipped and reported. Default model names are starting points — override per provider as needed.
- **LLM judge** (`judge.py`): grades open-ended (rubric) tasks — CoT-then-score, 1–5 per criterion,
  reference-guided, temperature 0, pinned `JUDGE_PROMPT_VERSION`. Default judge is **Claude**, with
  **GPT as the fallback for Claude's own answers** (a model never judges its own family —
  self-preference bias). Needs `ANTHROPIC_API_KEY`; without it, rubric tasks score 0 (`--no-judge`).
- These are **billed** by each provider. Start small: a couple of task ids, `--repeats 1`, a few
  providers — check cost/latency before a larger sweep.

Auth: pass `--token` or set `PERSONALAI_AUTH_TOKEN` (only needed if the backend requires a token).
Output: `results.json` (full per-run bundle + reproducibility metadata) and `leaderboard.md`.

## How it works

- **Tasks** (`tasks/*.yaml`) — declarative: `id, category, capability_tier, input, expected|rubric,
  version, metadata`. Independent of any model. Grading: `expected` (programmatic; `metadata.match` =
  `includes` (default) | `exact` | `regex`) or `rubric: {type: model_graded, criteria: ...}` (LLM
  judge — Phase 2).
- **Modes** (`modes.py`) — named override sets sent to `/assistant/execute`, each with a
  `capability_tier`. Phase 1: `single_no_tools`, `single_tools_mcp`, `multi_tools_mcp`, plus
  **memory-on** variants (`*_memory`).
- **Adapters** (`adapters.py`) — `PersonalIAAdapter` calls the endpoint; the `SystemUnderTest`
  protocol lets Phase 2 frontier adapters slot in unchanged.
- **Scoring** (`scoring.py`) — `exact` / `includes` / `regex` now; `model_graded` (injected judge).
- **Runner / report** — runs tasks × modes, records each result with reproducibility metadata (git
  commit, timestamp, platform), and renders a tier-grouped Markdown leaderboard + JSON.

## Fairness

Results are grouped by **capability tier** and never averaged across tiers — a tool-equipped or
multi-agent run is never compared head-to-head with a raw single-agent run. Memory on/off is its own
axis: a memory-on mode gets a `…+memory` tier so it isn't blended with the memory-off result.

## Extending

- **Add a task**: drop a `*.yaml` file in `tasks/` (one task or a list). Give it a unique `id`, a
  `category`, a `capability_tier`, and either `expected` or a `rubric`.
- **Add a mode**: add a `Mode(...)` in `modes.py` and register it in `ALL_MODES`. Use `with_memory(...)`
  for a memory-on variant.
- **Add a provider/system** (Phase 2): implement the `SystemUnderTest` protocol (a `name` + a
  `run(messages, overrides) -> RunResult`) and pass it to `run_suite`.

## Reading the leaderboard

Each tier lists its modes with **pass@k** (fraction of tasks any attempt solved — capability) and
**pass-rate** (fraction of all attempts that passed — reliability), plus mean latency. With
`--repeats 1` the two are identical; with more repeats they diverge for stochastic models. The
per-task matrix shows `passes/attempts` per cell; a Failures section lists cells that never passed,
and a Flaky section lists cells that passed some attempts but not all. Compare *within* a tier;
compare tiers side by side, not by a blended average.

### Raw-LLM vs assistant-mode (Phase 2)

Phase 1 only benchmarks personalIA (assistant mode). Phase 2 adds raw-LLM adapters (frontier APIs
with no tools/memory) under a `raw` tier and tool-equipped wrappers under the matching tool tiers, so
the leaderboard can show "raw model" vs "full assistant" honestly, labelled by capability.
