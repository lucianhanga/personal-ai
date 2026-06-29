---
name: project-model-suite-presets
description: Design for hardware-recommended model-suite presets in Settings>Preferences — platform detection, one-click preset apply, 5-layer per-layer override, install/memory states, and the backend signal gaps it needs
metadata:
  type: project
---

Reworked `apps/ui/src/Preferences.tsx` (2026-06-29 SPEC) to add a **Model suite** card at the TOP of the Preferences section. Goal: a local-first user gets a correct, runnable model stack for the machine they are on in one click, with full per-layer override.

**Shape:** PlatformBanner ("Detected: <device> · <mem> · <accelerator>") -> radio-group of preset cards (Max quality / Balanced / Custom) with a Recommended (or "Nearest match") badge -> primary "Use recommended for this machine" -> MemoryFitMeter (est suite mem vs detected) -> LayerOverrideList of 5 rows. Changing any one layer flips the suite to "Custom (modified from <preset>)" with a one-click "Reset to <preset>".

**5 layers -> config mapping (and the gaps that BLOCK persistence):**
1. Chat LLM -> `default_model` (+ `ollama_num_ctx`). CRITICAL: this is the SAME persisted field the top bar owns ([[model-selection-topbar-decision]]); the suite Chat row and the top bar must be one value, never a second picker.
2. Embedding -> `embed_model` exists; **`embed_dim` does NOT exist** — backend must add. Fold the legacy "Document indexing engine" embedding field into a read-through of this layer (avoid two embedding pickers).
3. Reranker -> **`rerank_model` + `rerank_enabled` do NOT exist in TenantSettings** — backend must add.
4. NER (GLiNER2) -> **no settings field** — backend must add (e.g. `ner_model`).
5. Relations (GLiREL) -> **no settings field** — backend must add (e.g. `relation_model`).

**Two shipped presets:** A100 80GB "Max quality" (~69GB: qwen3.6:27b@256K, Qwen3-Embedding-8B@4096, Qwen3-Reranker-8B warm, GLiNER2-large, GLiREL-large) and M4 Pro 48GB "Balanced" (~33-37GB: qwen3.6:27b@32K, Qwen3-Embedding-4B@2048, Qwen3-Reranker-0.6B on-demand, same NER/relations). Plus "Custom".

**Backend signals to flag to backend-api-architect (most don't exist yet):**
- `GET /api/v1/platform` -> total_memory_bytes, accelerator (cuda/metal/rocm/cpu), device_name, free/admission-budget. Backend already measures total mem + global Ollama load (admission budget). Must degrade: partial is fine.
- `GET /api/v1/models/status` -> per model {id, kind, installed, loaded, size_bytes?} covering Ollama pulls AND in-process HF weights. This powers the Installed/Not-installed pill that fixes the live "default model not installed" silent crash.
- `GET /api/v1/model-presets` -> catalog w/ per-layer model+ctx+dim+on/off and per-preset/per-layer mem estimates + target-hardware label. Keep estimates honest server-side.
- `POST /api/v1/models/pull {id}` (streamed progress), optional; UI degrades to a copyable `ollama pull <id>` command.

**Hard UX rules:** never block chatting; Save allowed with not-installed models but warns pre-save; apply-confirm dialog only when pulling uninstalled models OR exceeding memory (ALWAYS for unrecognized machines). Status is text-not-color-only. Preset cards = keyboard radio group; apply dialog focus-trapped; suite-flip + install results via aria-live. MemoryFitMeter reuses ContextMeter.tsx fill-threshold helper. Reuse Preferences.tsx palette (OK #1a7f37 / ERR #b00 / WARN #b06f00), Field primitives, header Save/Reset/dirty-saved.

See [[project-ui-architecture]] (section rail, loading/empty/error, testid conventions), [[model-selection-topbar-decision]] (chat-model single-source-of-truth), [[project-knowledge-section]] (sibling Settings section patterns).
