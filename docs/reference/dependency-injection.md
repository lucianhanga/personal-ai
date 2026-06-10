# Dependency Injection & Registries

PersonalAI wires adapters to the core through **registries** and a **composition root**
(ADR-0001). The rule: *adding a capability = registering an adapter*. The core never imports a
concrete adapter; it only depends on the ports in `personalai_contracts`.

> Status: the registry/DI machinery lands in M0-4. Concrete adapters (Ollama, pgvector, ...) are
> registered from M0-5 onward.

## Pieces

| Piece | Module | Role |
|---|---|---|
| `Registry[T]` | `personalai_core.registry` | A name -> adapter map for one port; fail-closed `get`. |
| `Registries` | `personalai_core.registries` | One registry per backend seam (providers, retrievers, vector/object/graph stores, modality handlers, agent roles, tools). |
| `CoreConfig` | `personalai_core.config` | Config-driven selection of the active singleton adapters + local-first defaults (`bind_host=127.0.0.1`, `egress_enabled=False`). Reads `PERSONALAI_*` env. |
| `bootstrap` | `personalai_backend.composition` | The composition root: build config + registries, register adapters, return wiring. Resolves the active adapter for each seam by name via `registries.<seam>.get(config.<name>)` (fail-closed). |

UI renderers are a frontend seam and are registered in the SPA (M0-6), not in the Python registries.

## How to add an adapter

1. Implement the relevant port (see [Contracts & ports](./contracts-and-ports.md)) in its seam
   package (e.g. `providers/ollama`). Depend inward on `personalai_contracts` only.
2. Register it in the composition root's `register_adapters` (in
   `apps/backend/src/personalai_backend/composition.py`):
   ```python
   from personalai_providers.ollama import OllamaProvider
   registries.model_providers.register("ollama", OllamaProvider(...))
   ```
3. Select it via config (default or `PERSONALAI_MODEL_PROVIDER=ollama`).
4. Add tests. Swapping or adding an adapter must require **no change to the core**.

## Selection & fail-closed behavior

```python
from personalai_backend import bootstrap

boot = bootstrap()                      # config from PERSONALAI_* env + populated registries
# The composition root / endpoints resolve the active adapter by name, fail-closed:
provider = boot.registries.model_providers.get(boot.config.model_provider)
```

If a configured adapter name is not registered, `Registry.get` raises
`RegistryError` (fail-closed) rather than silently degrading.

## Singletons vs collections

- **Singletons** (config selects one active): model provider, retriever, vector repository,
  object store. Resolved by name from their registry at the composition root / per request.
- **Collections** (many enabled at once): tools, agent roles, modality handlers. Used directly
  from the registries per request (selection happens at call time, e.g. by the Tool/MCP gateway).
