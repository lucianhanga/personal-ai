# core (`personalai_core`)

The PersonalAI **core**: agent orchestration, the Tool/MCP gateway, the security/policy
engine, structured-output validation, and the **registries** that discover adapters.

- Depends **only** on `personalai_contracts`.
- Must **not** import `personalai_backend` or any concrete adapter package.
- Holds the registries and DI wiring that compose adapters behind their ports.
