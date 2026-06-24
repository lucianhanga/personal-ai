---
name: project-panels-redesign
description: Design decisions for the Context/Inspector/Logs sidebar redesign and per-turn tool I/O disclosure (PersonalAI chat UI)
metadata:
  type: project
---

Spec'd a UX upgrade for the Context and Activity/Trace panels (apps/ui/src).

Key decisions (carry forward to any future panel/trace work):
- Right sidebar should become a 3-tab panel: **Context** (live composition, restyled ContextMeter), **Inspector** (per-turn history browser — new TurnInspector), **Logs** (existing ToolLog+AppLogs). Replaces the loose buttons in SidePanel.tsx.
- Tool I/O disclosure pattern: pair each `tool_call` with its following `tool_result` into ONE collapsible "tool chip" (Level 1: one line name+primary-arg+status pill; Level 2: expanded Request/Response card; Level 3: bounded "show full"). New shared components `ToolIO` + `JsonPayload`, used BOTH inline in MessageDetails and in the Inspector.
- Payload rules: truncate preview ~1.5KB / ~24 lines, copy yields FULL untruncated raw JSON, all scroll regions max-height ~16em bounded so page width/height never blows out; raw/pretty + wrap toggles.
- Context composition gets plain-language per-source explanations (System/Memory/Documents/History/Tools/Question) via a `?` popover; whole composition collapsible (persist in localStorage). The existing ContextMeter hover tooltip is mouse-only — must add focus + tap support (accessibility gap).
- Turn grouping in transcript: tinted USER block bg `#eef3fb`, text `#1f2937` (>=12:1), left accent `#4a90d9` 3px; assistant block white; optional even-turn wash `#fafbfc`; streaming turn amber top accent `#b06f00`.
- Muted-text fix: `#999` on white fails AA (~2.8:1); use `#6b7280` (~4.6:1) for anything a user must read; keep `#999`/`#888` decorative only.

**Persistence gap (item 3):** trace + usage are already in `MessageMeta` (meta.trace, meta.usage), but per-turn `ContextBreakdown` is only streamed live, NOT persisted. To show historic context composition in the Inspector, backend must persist a `meta.context` snapshot. Without it, Inspector shows trace+I/O+usage for all turns + "not captured" for context on older turns. Flag to [[backend-api-architect]] / ui-developer.

See [[project-ui-architecture]] and [[project-usage-metrics]] for the existing conventions this builds on (reuse fmt/fmtMs/compactTok/approxTokens, fill thresholds <70 green/<90 amber/>=90 red, TRACE color maps from MessageDetails.tsx, agentColors).
