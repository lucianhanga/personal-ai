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

# Sweep a whole price/quality tier across providers (cheapest | medium | best | all):
uv run --env-file .env python -m personalai_benchmarks compare --no-personalia --model-tier best

# Prefer clicking over flags? Open the local launcher UI (dev-only, localhost, no auth):
uv run --env-file .env python -m personalai_benchmarks ui   # then open http://127.0.0.1:8900/
make run-bench-ui                                           # same thing, from the repo root
```

### Launcher UI

`ui` serves a small localhost page (Python stdlib only) where you tick providers, modes, tasks and
options; it shows the generated `compare` command, runs it, streams the live stdout/stderr into a log
window (SSE), and links the resulting `leaderboard.html`. The run subprocess is built from a
validated arg list (no shell), and the server binds `127.0.0.1` only — it is a developer convenience,
not part of the secured app. Run it with `--env-file .env` so the spawned `compare` inherits the
frontier API keys.

**Stopping early.** Press **Ctrl-C** during a CLI run — or click **Stop** in the launcher (it sends
`SIGINT`, not a kill) — and the harness writes a **partial report** from whatever finished, marked
`PARTIAL` / "Partial run" in the output and both reports. Handy for long `--model-tier all` sweeps:
stop once you've seen enough and still get a leaderboard of the results so far.

## Phase 2: frontier comparison + LLM judge

`compare` runs PersonalAI (across its modes) **and** each frontier model that has an API key (raw
tier) over the same tasks, then writes one combined leaderboard grouped by capability tier.

- **Providers** (`frontier.py`): one OpenAI-compatible adapter reaches OpenAI / Anthropic / DeepSeek
  / xAI (Grok) / Groq / Gemini. Keys come from the environment (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  `DEEPSEEK_API_KEY`, `XAI_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`); a provider without a key is
  skipped and reported.
- **Model lineup + `--model-tier`**: each provider carries a curated lineup tagged `cheapest` /
  `medium` / `best` (up to 5 models, current + older, validated against each provider's live
  `/models`; DeepSeek has 2 and xAI 4, not padded). `compare --model-tier cheapest|medium|best`
  runs just that tier across providers, `--model-tier all` runs the full spread (more cost), and the
  **default** runs a single representative per provider (unchanged cost). With the cost + quality
  bars, this is the artificialanalysis-style cheapest→best comparison. Model ids change fast — edit
  `PROVIDERS` in `frontier.py` and prices in `pricing.py` as they move.
- **LLM judge** (`judge.py`): grades open-ended (rubric) tasks — **form-filling** (a one-sentence
  justification is written *before* each criterion's 1–5 score, the G-Eval pattern, for steadier and
  auditable grades), reference-guided, temperature 0, pinned `JUDGE_PROMPT_VERSION` (now `v2`; parsing
  still tolerates the older bare-integer shape). Default judge is **Claude**, with **GPT as the
  fallback for Claude's own answers** (a model never judges its own family — self-preference bias).
  Needs `ANTHROPIC_API_KEY`; without it, rubric tasks score 0 (`--no-judge`).
- **Length-bias check** (`analysis.py`): every `compare` run reports the Pearson correlation between
  answer word-count and judge score across judged answers, and **flags** a strong correlation — a
  tell-tale of verbosity bias. It prints in the summary and the Markdown report header.
- **Frontier result cache** (`cache.py`): frontier models are deterministic (temperature 0), so the
  *raw* frontier tier is **cached and reused across runs** — re-running `compare` re-runs only the
  **local model** (which changes constantly) and any **new tasks**; already-benchmarked frontier
  cells are served from `benchmark-results/cache.json` with no API call. The key folds in the task
  `version` and a grading fingerprint, so editing a task (bump its `version`) or changing the judge
  re-runs just that cell. Tool-equipped frontier runs depend on local tools, so they are not cached.
  `--no-cache` re-runs everything; `--refresh` re-runs frontier and refreshes the cache (use when a
  provider actually changes a model); `--cache-file` sets the path.
- These are **billed** by each provider. Start small: a couple of task ids, `--repeats 1`, a few
  providers — check cost/latency before a larger sweep.

Auth: pass `--token` or set `PERSONALAI_AUTH_TOKEN` (only needed if the backend requires a token).
Output: `results.json` (full per-run bundle + reproducibility metadata) and `leaderboard.md`.

## How it works

- **Tasks** (`tasks/*.yaml`) — declarative: `id, category, capability_tier, input, expected|rubric,
  version, metadata`. Independent of any model. Grading: `expected` (programmatic; `metadata.match` =
  `includes` (default) | `exact` | `regex`) or `rubric: {type: model_graded, criteria: ...}` (LLM
  judge — Phase 2). Beyond reasoning/tool-use/quality, `communication.yaml` covers everyday assistant
  work — **tone reformulation** (business / casual / friendly), **email composition** (subject +
  body from a brief), and **email reply**; each rubric scores named per-dimension 1–5 anchors against
  a reference answer and explicitly rewards content over length to curb the judge's verbosity bias.
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

**Visual comparison.** Each tier row carries a **quality bar** (mean score, 0–1, color-coded
green/amber/red) and a **Δ best** comparison mark — `best` for the tier leader, otherwise the signed
gap to it (e.g. `-0.20`). Below each tier table the HTML report draws a horizontal **bar chart** of
mean score per system (artificialanalysis-style), so the spread is readable at a glance; the Markdown
report uses a text bar for the same.

### Raw-LLM vs assistant-mode (Phase 2)

Phase 1 only benchmarks personalIA (assistant mode). Phase 2 adds raw-LLM adapters (frontier APIs
with no tools/memory) under a `raw` tier and tool-equipped wrappers under the matching tool tiers, so
the leaderboard can show "raw model" vs "full assistant" honestly, labelled by capability.
