# Memory index

- [PersonalAI UI architecture](project_ui_architecture.md) — React+Vite SPA, Settings accordion for config + right-hand Panels sidebar for per-chat observability; reuse testid/status-color/loading-empty-error conventions
- [Model selection = top bar, persisted](project_model_selection_topbar.md) — single model/provider control in top bar that persists via PUT /api/v1/settings; Preferences keeps only endpoint/embedding config
- [Top-bar + composer conventions](feedback_topbar_composer.md) — no token input in local mode, no glyphs (color dots instead), 4-line composer with Enter-to-send / Shift+Enter newline
- [Usage metrics display](project_usage_metrics.md) — per-turn token+time footer in transcript vs per-chat totals in Context panel; reuse fmt/fmtMs/fill-threshold helpers from ContextMeter.tsx
- [Panels redesign + tool I/O disclosure](project_panels_redesign.md) — 3-tab sidebar (Context/Inspector/Logs), paired tool-chip ToolIO progressive disclosure, turn-grouped transcript, context explanations; meta.context persistence gap
- [Audio attachment chips](project_audio_attachment_chips.md) — #406: drag-drop-only audio becomes chips mirroring attachedImages; hover/focus/tap panel + Copy; transcript folds into sent message as [Audio: name] blocks; Summarize dropped
- [Resource activities in timeline](project_resource_activities.md) — #424: image/doc/audio processing = new `resource` node (teal #0d7d7d, ToolIO disclosure) in ActivityTimeline; live pre-turn cluster + persisted meta.activities at top of turn by ts
- [RAG pipeline in timeline](project_rag_timeline.md) — #437: indexing/retrieval/ner kinds (amber-olive/indigo/fuchsia) prepended to assistant meta.trace; one RAG filter chip; new RetrievalIO citation list; ner dormant til Phase 6
