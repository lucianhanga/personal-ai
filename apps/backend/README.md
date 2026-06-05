# apps/backend (`personalai_backend`)

The PersonalAI **backend application** — the FastAPI composition root that selects concrete
adapters from the core registries and exposes the loopback API.

- Depends on `personalai_core` and `personalai_contracts`.
- This is the **outermost** Python layer; nothing imports it.
- The FastAPI app (loopback bind, auth stub, /health) lands in **M0-5**; this milestone (M0-1)
  only establishes the package.
