---
name: model-selection-topbar-decision
description: UX decision that model/provider selection lives only in the top bar and persists; Preferences keeps only endpoint/embedding config
metadata:
  type: project
---

Model selection consolidation decision (redesign SPEC, 2026-06-18):

Top bar provider+model `<select>`s are the SINGLE source of truth for "which chat model" and they PERSIST the choice via `PUT /api/v1/settings` (`saveSettings(token, {default_model})` / `{model_provider}`). `default_model` and `model_provider` were REMOVED from Settings -> Preferences.

**Why:** local-first single-user app (app_mode=local); two controls (ephemeral top-bar vs persisted Preferences) caused the "pick model, reload, it reverts" confusion. Backend already overlays persisted defaults onto `/api/v1/providers` and `/api/v1/models`, so the top bar is already seeded from the persisted value — making the selector write back closes the loop with no new concept.

**How to apply:** Preferences "Provider (advanced)" should keep only endpoint/embedding config (`ollama_host`, `embed_provider`, `embed_model`, `openai_base_url`) plus the relocated legacy token field. Never re-introduce a second model picker. Persistence write-back is fire-and-forget with amber Saving / green Saved / red "Not saved" status; never block chatting on it.

Related top-bar/composer rules: [[topbar-composer-conventions]]. Reuse status palette/conventions: [[project_ui_architecture]].
