# Remote / Frontier Providers (M2)

PersonalAI is local-first, but you can **opt into** a remote OpenAI-compatible provider (OpenAI,
Azure OpenAI, Together, Groq, OpenRouter, or a local vLLM/llama.cpp server). It plugs into the same
`ModelProvider` seam as Ollama, behind the egress + secrets controls.

> Remote usage sends your prompts off the machine. It is **off by default** and fails closed: a
> remote call is refused unless you explicitly enable egress and allowlist the provider host.

## Enable OpenAI

Set these (e.g. in a local, gitignored `.env`):

```bash
PERSONALAI_AUTH_TOKEN=demo
PERSONALAI_OPENAI_API_KEY=sk-...            # secret — never commit; rotate if exposed
PERSONALAI_OPENAI_BASE_URL=https://api.openai.com/v1
PERSONALAI_EGRESS_ENABLED=true              # remote calls require egress on
PERSONALAI_ALLOWED_EGRESS_HOSTS=api.openai.com
```

Then run the backend (`make run-backend` — it auto-loads `.env` on startup) and the UI. The
**Provider** dropdown now offers `openai` alongside `ollama`; pick a model (e.g. `gpt-4o-mini`) and
chat. Each model shows a **local/remote** badge. Provider/model and the egress allowlist can also be
set **per-tenant** in **Settings → Preferences / Network** (overlaying these env defaults).

## Other OpenAI-compatible runtimes

The same adapter works for anything that speaks the OpenAI Chat Completions API — just change the
base URL (and allowlist the host):

| Target | `PERSONALAI_OPENAI_BASE_URL` | Egress host |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `api.openai.com` |
| Azure OpenAI | your Azure endpoint `/openai/deployments/...` | your Azure host |
| Together / Groq / OpenRouter | the provider's `/v1` | provider host |
| **local vLLM / llama.cpp** (OpenAI mode) | `http://127.0.0.1:8000/v1` | loopback (always allowed) |

So **vLLM and llama.cpp** are covered without a separate adapter: run them in OpenAI-compatible
mode and point `PERSONALAI_OPENAI_BASE_URL` at the local server (loopback needs no egress).

## How it stays safe

- **Egress allowlist:** every remote call runs the egress guard first; with egress off or the host
  not allow-listed, it fails closed (no silent off-machine calls). Enabling egress with an **empty
  allowlist denies all hosts** — you must list the provider in `PERSONALAI_ALLOWED_EGRESS_HOSTS`
  (or set `PERSONALAI_EGRESS_ALLOW_ANY=true` to opt into open egress).
- **API key:** injected from config/env, never hard-coded, never logged (redaction).
- **Audit:** remote calls are recorded (redacted) in the audit log.
- **Local-first default:** `PERSONALAI_MODEL_PROVIDER` defaults to `ollama`; remote is per-request
  or via config.

## Verify against a real API (opt-in)

```bash
PERSONALAI_OPENAI_IT=1 PERSONALAI_OPENAI_API_KEY=sk-... \
  uv run pytest providers/openai_compat/tests/test_integration.py -q
```
(Skipped in CI. Override models with `PERSONALAI_OPENAI_IT_MODEL` / `PERSONALAI_OPENAI_IT_EMBED`.)

## Cost & privacy

Remote models bill per token and send your data to the provider. Prefer local models
([local chat guide](./local-chat.md)) for private/offline use; use remote for frontier capability.
