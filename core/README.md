# core (`personalai_core`)

The PersonalAI **core**: agent orchestration, the Tool/MCP gateway, the security/policy
engine, structured-output validation, and the **registries** that discover adapters.

- Depends **only** on `personalai_contracts`.
- Must **not** import `personalai_backend` or any concrete adapter package.
- Registries + DI wiring land in **M0-4**; this milestone (M0-1) only establishes the package.
