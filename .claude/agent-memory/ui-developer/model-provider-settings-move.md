---
name: model-provider-settings-move
description: Model/provider/reasoning controls are in Settings->Agents Defaults only; chat composer has zero model UI
metadata:
  type: project
---

All model, provider, and reasoning controls were moved out of Chat.tsx into Settings -> Agents "Defaults" fieldset (feat/reasoning-levels branch, June 2026). The move is COMPLETE:

- `Chat.tsx`: No `provider`, `model`, `models`, `providers` state; no `fetchProviders`/`fetchModels` calls; no model-indicator, provider-select, model-caps, or vision-hint elements in the JSX.
- `Agents.tsx`: `agents-defaults` fieldset contains three selects: Provider (`agents-default-provider`, bound to `TenantSettings.model_provider`), Default model (`agents-default-model`), Default reasoning (`agents-default-reasoning`).
- `streamChat` and `resumeChat` no longer receive a `provider` argument from Chat.tsx; backend uses tenant defaults.
- Image descriptions are always folded into message content (`[Image: desc]`) regardless of model capabilities. The backend decides whether to use the image directly (vision model) or the text description.
- Send button and send() guard no longer check `!model`.

**Why:** Backend uses tenant default_model/model_provider from TenantSettings for every turn; per-turn model/provider override from the frontend is no longer needed.

**How to apply:** Do not re-introduce any model/provider/reasoning elements into Chat.tsx. All model config lives in Agents.tsx defaults. [[personalai-ui-stack]]
