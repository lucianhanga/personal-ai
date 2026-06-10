---
name: project-ui-architecture
description: PersonalAI frontend stack, layout model, and UI conventions for design work
metadata:
  type: project
---

PersonalAI UI is a React + Vite SPA, single-user (token auth), local-first. No component library — inline styles, `data-testid` on everything.

Layout model (in `apps/ui/src/Chat.tsx`):
- A collapsible **Settings accordion** holds global config rows: Documents, Tools, Memory, Reasoning, MCP servers. Each row is a one-line flex with a show/hide button + a toggle/select.
- A 3-column **workspace**: chats list | chat | right-hand **Panels sidebar** (`aside data-testid="side-panel"`). Sidebar holds per-conversation observability: Activity (`ToolLog`), App logs (`AppLogs`), plus a `ContextMeter`. Sidebar panels take `token` + `conversationId` and have manual `[Refresh]`.

UI conventions to reuse:
- Bordered card, ~0.8rem font for config panels (`McpPanel.tsx`); monospace log lines + `maxHeight` scroll + Loading/empty/error trio for log panels (`AppLogs.tsx`).
- Status color map: green = healthy/connected/success, red = error, amber/yellow = warning. (Matches user's global CLAUDE.md.)
- Risk gate: actions that run local programs use a confirm-before-run (currently `window.confirm`). MCP tools are HIGH-risk and need approval to run.

**Why:** These are the shared patterns any new UI must match to feel native.
**How to apply:** For new config UIs put them in/launched-from Settings; for observability put them in the Panels sidebar as a sibling of Activity/App logs. Reuse the testid + status-color + loading/empty/error conventions.
