# providers/openai_compat (`personalai_provider_openai`)

A `ModelProvider` adapter (ADR-0002) for **OpenAI-compatible** HTTP APIs — OpenAI, Azure OpenAI,
and runtimes that expose the OpenAI Chat Completions API (Together, Groq, OpenRouter, local vLLM).
Depends inward on `personalai_contracts` only (ADR-0001).

This is a **remote** provider:

- Every network call first runs an injected **`egress_guard(host)`** (the backend wires it to the
  egress allowlist; adapters cannot import the core, so the guard is injected). With no guard it
  makes the call directly (used in tests).
- The **API key** is injected at construction, never hard-coded, and never logged.
- `capabilities()` is best-effort (remote APIs expose no capability endpoint); `list_models()`
  reports `local=False`.

Wired into config/egress/secrets and registered in the composition root in **M2-2**.
