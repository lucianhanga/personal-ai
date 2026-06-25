---
name: project-resource-activities
description: UX design (#424) for surfacing eager resource-processing (image describe / doc extract / audio transcribe) as Activity-timeline events, live + persisted
metadata:
  type: project
---

Designed the presentation for #424: eager resource-processing (image-describe, doc-extract, audio-transcribe) becomes a first-class **resource activity** in the existing `ActivityTimeline` (NOT a new panel). Architect owns the `{kind:"resource", action, text, ts, model, ms, ref}` contract; backend owns persisting it on the USER turn `meta["activities"]`. I designed presentation only.

Key decisions (carry forward to any resource/activity work):
- **New node category** `resource` added to ActivityTimeline's `NodeKind` (`context|tool|reasoning` today) + a new `Resources` filter chip + `All`. Distinct hue **teal #0d7d7d** (AA on white ~4.7:1), faint `#e6f4f4` wash — separable from tool violet #7c3aed, context accent #4a90d9, planner blue, researcher gray, critic amber.
- **Resource node reuses the `ToolIO` disclosure shell** (Tier-1 button `aria-expanded` summary: caret + `Resource` label + action+ref + StatusPill; Tier-2: `Model:` + `Duration: fmtMs(ms)` + `Resource: ref`). Per-step `ts` line above the chip via existing `clockFromTs(ts)||turnClock`. New `ResourceIO`-style component modeled on ToolIO.
- **Label wording by `action`:** `image_described`→"Described image — {ref}", `document_extracted`→"Extracted document — {ref}", `audio_transcribed`→"Transcribed audio — {ref}".
- **Three node states** in progress(amber)/done(green)/error(red) via StatusPill (words+color, never color-only). Chip-status vocab differs per type and folds in: image `done` / audio `done`+`empty` / doc `small`+`large` → node **done**; any `error`→**error**. Doc `large` still = done node (its "RAG soon" warning stays on the chip).
- **Live = a pre-turn cluster.** Before submit, a synthetic top group `Preparing your message` (`data-testid="timeline-preturn"`, default open, `role="status"` at cluster level, pulsing `live` header dot) mirrors the chip overlay states. Chat.tsx derives a `liveActivities` array from its existing `imageAttachments/audioAttachments/documentAttachments` state and passes it Chat→SidePanel→ActivityTimeline (new prop). On SUBMIT the cluster disappears and the same activities re-render under the committed turn from `meta.activities` — stable by `ref`+`ts`, no reorder flicker.
- **History ordering:** persisted `meta["activities"]` render at the TOP of their turn's spine (resource = question-time input), ordered by `ts` asc, BEFORE the existing `Context assembled` node, then tools/reasoning. ActivityTimeline already resolves a turn's preceding user message (for the question) — reuse that lookup to read `.meta.activities`. Turn-header meta gains an optional `N resource(s)` segment.
- **Empty/legacy:** turns without `activities` render exactly as today — nothing new, no empty state.

Reuse helpers verbatim: `fmtMs`, `clockFromTs`/`clockUTC`, `compactTok`, `relTime`, `READABLE` #6b7280, the spine-dot mechanism, StatusPill, classical monochrome-SVG icons (`stroke=currentColor`, 24-box). See [[project-panels-redesign]] (ToolIO disclosure + timeline), [[project-audio-attachment-chips]] (chip state machine), [[project-usage-metrics]] (fmtMs/compactTok). Posted to issue #424. Handed to [[ui-developer]]; backend+architect own contract/persistence.
