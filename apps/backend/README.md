# apps/backend (`personalai_backend`)

The PersonalAI **backend application** — the FastAPI composition root that selects concrete
adapters from the core registries and exposes the loopback API.

- Depends on `personalai_core` and `personalai_contracts`.
- This is the **outermost** Python layer; nothing imports it.
- Exposes the loopback `/api/v1` API (binds `127.0.0.1`) with auth and `/health`.
