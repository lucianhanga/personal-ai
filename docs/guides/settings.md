# Settings: per-tenant preferences (M8.2)

PersonalAI persists per-tenant **preferences** that overlay the boot-time deployment config for each
request. The UI is a **Chat | Settings** two-view split; the **Settings** view groups them into
panels: **Documents, Tools, MCP, Agents, Memory, Network, Preferences**.

Every preference is optional: an unset field (`null`) means *inherit the deployment default*, so the
overlay only applies the values you set. Server/boot/secret config — `AUTH_TOKEN`, `DATABASE_URL`,
`OPENAI_API_KEY`, `APP_MODE`, bind host/port, CORS origins, sessions, the audit sink — stays
environment-only and is never exposed through the settings API.

## What you can set

| Group | Fields (`TenantSettings`) |
|---|---|
| **Models** | `model_provider`, `default_model`, `ollama_host`, `ollama_num_ctx`, `ollama_keep_alive`, `embed_provider`, `embed_model`, `openai_base_url` |
| **Agents** | `agent_mode` (`single`/`multi`/`custom`), `agent_graph_enabled` (legacy), `agent_human_gate`, `agent_accuracy_mode`, `agent_max_iterations`, `agent_timeout_seconds` |
| **Behaviour** | `memory_enabled`, `grounding_enabled`, `max_upload_bytes` |
| **Network egress** | `egress_enabled`, `allowed_egress_hosts` |

Field names match `CoreConfig` exactly, so the overlay is a plain `model_copy(update=...)`. The
**Agents** panel additionally edits per-agent system prompts and the researcher's tool scope — see
[the agent guide](./agent.md#per-agent-configuration-settings--agents).

## API

```bash
# Read the saved overrides plus the effective defaults (so the UI can show inherited values):
curl -H "Authorization: Bearer demo" http://127.0.0.1:8765/api/v1/settings

# Full overwrite of this tenant's overrides (omit a field, or send null, to restore its default):
curl -X PUT http://127.0.0.1:8765/api/v1/settings -H "Authorization: Bearer demo" \
  -H "Content-Type: application/json" \
  -d '{"agent_mode":"multi","agent_timeout_seconds":600}'

# Interactive allow-on-deny: enable egress and append one host to the allowlist (one-click in the
# reasoning pane when a tool is blocked), then re-send the request:
curl -X POST http://127.0.0.1:8765/api/v1/settings/egress/allow -H "Authorization: Bearer demo" \
  -H "Content-Type: application/json" -d '{"host":"example.com"}'
```

`PUT` validates bounds and enums via the `TenantSettings` contract. The egress host must be a **bare
lowercase hostname** (no scheme, path, or whitespace). Per-agent config lives at
`GET`/`PUT /api/v1/agents/config` ([agent guide](./agent.md#per-agent-configuration-settings--agents)).

## How the overlay works

Each request loads the tenant's saved settings through a tenant-bound store (Postgres RLS, so a
tenant only ever sees its own row) and overlays them onto the boot `CoreConfig`; with no database
configured/reachable, the boot config is used unchanged. The result drives that turn — including the
**per-tenant egress** enforced for in-process tools (a `current_egress` contextvar set for the turn).

## Storage

Per-tenant settings are persisted by migrations (all tenant-scoped, RLS):

| Migration | Adds |
|---|---|
| `0015_tenant_settings.sql` | the `tenant_settings` table |
| `0016_agent_config.sql` | `agent_mode` + the `tenant_agent_config` table (per-agent prompts/tools) |
| `0017_tenant_egress_settings.sql` | `egress_enabled` + `allowed_egress_hosts` columns |
| `0018_tenant_agent_timeout.sql` | the `agent_timeout_seconds` column |

## Deployment defaults

The boot defaults for every preference come from the `PERSONALAI_*` environment variables documented
in the per-feature guides ([local chat](./local-chat.md), [remote providers](./remote-providers.md),
[files + RAG](./files-and-rag.md), [memory](./memory.md), [the agent](./agent.md)). The backend
**auto-loads a local `.env`** on startup (real environment variables still win).
