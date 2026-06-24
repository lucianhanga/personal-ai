---
name: project-usage-metrics
description: How PersonalAI displays token+time usage — per-turn footer in transcript vs per-chat totals in the Context panel, with shared formatting helpers
metadata:
  type: project
---

Token + time usage metrics in the chat UI follow a deliberate two-surface split:

- **Per-turn (per question):** a subtle always-visible footer line under each assistant message. At rest shows compact total tokens + time + colored context-fill % (`◍ 6.0k tok · 2.3 s · ▣ 25%`). Hover/focus reveals the full prompt/reply/total/time/window card. Footer omitted entirely when a turn has no usage data (old history).
- **Per-chat (whole conversation):** primary home is the side `ContextMeter` panel "Chat total" line + an "avg / turn" sub-line. Optional secondary: compact total-tokens chip on the conversation-list item.

**Why:** user wants tokens+time per question "at a glance" (so it must be in the transcript, not hover-only or panel-only), while keeping whole-chat totals discoverable but unobtrusive. Each surface gets a distinct framing word ("Window" = latest turn, "Chat total"/"avg" = whole chat) so a matching number like `2.3 s` never reads as a confusing duplicate. The prompt/reply split lives in the panel + footer-hover, never at-rest in both.

**How to apply:** when extending usage/metrics UI, reuse `fmt` (exact, thousands sep), `fmtMs` (`820 ms`/`2.3 s`/`1m 5s`), and the green/amber/red fill thresholds (<70 green `#2a9d4a`, <90 amber `#b06f00`, >=90 red `#b00`) already in `apps/ui/src/ContextMeter.tsx`. Add `fmtCompact` (abbreviate `12.4k` at >=10000) for at-rest footer + list chip only. Metrics must render identically for live-streaming and loaded-historical turns from persisted per-turn UsageInfo; totals/avg summed at load, turns missing data excluded and total marked partial. See [[project-ui-architecture]].
