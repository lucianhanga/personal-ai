---
name: project-audio-attachment-chips
description: Audio transcription UX revision (#406) — drag-drop-only audio becomes attachment chips mirroring attachedImages, transcript folds into sent message as labeled blocks
metadata:
  type: project
---

Audio transcription in the chat composer was revised (#406, revising #389) from "transcript auto-injected into the textarea + global Summarize button + ♪ file-picker button" to an **attachment-chip model** that mirrors the existing `attachedImages` thumbnail pattern.

Key decisions (the spec the ui-developer implements):
- **Drag-and-drop ONLY.** The `♪` `audio-file-btn` + hidden `audio-file-input` are removed. Audio is added by dropping on `composer-dropzone` (Chat.tsx ~1333), same as images.
- **Audio chips** render in a new `data-testid="audio-attachments"` flex row ABOVE the `image-attachments` row (do not merge the two). State machine: `transcribing` (amber `#b06f00`, spinner) → `done` (accent `#4a90d9` glyph + filename + ~60-char snippet+"…") → `empty` ("no speech detected", muted) → `error` (red `#b00020`, short text + Retry for non-413). Glyph = `♪` (the project's established non-emoji audio glyph). Chip is `tabIndex=0` focusable, has a `×` `remove-audio-{id}`.
- **Floating panel** on hover OR focus OR tap (hover-only is an a11y fail) shows the full scrollable transcript (`max-height:240px`) + a Copy button. Copy REUSES the `JsonPayload.tsx` (44-79) pattern verbatim: `navigator.clipboard.writeText`, "Copied" for 1200ms, silent catch. Panel flips above the chip near viewport bottom, clamps to composer right edge. `role="dialog"` when pinned (tap), Escape closes + returns focus.
- **Send-flow = Option (b):** on send, each `done` transcript folds into `message.content` as a labeled block `[Audio: {name}]\n{transcript}` after the typed text; images still ride on `message.images`; `empty`/`error` chips contribute nothing. Block send while any chip is `transcribing` (amber `role="status"` note). See [[project_usage_metrics]] for the per-turn footer that the sent message produces.
- **Summarize one-tap (#389) is DROPPED** from the global composer (it was coupled to the old textarea-injection model). If product insists, fold it into the chip's panel as a per-chip Summarize via the existing `send(override)` path.
- **State shape:** `audioAttachments: {id,name,status,transcript,error?,file?,canRetry?}[]` mirroring `attachedImages`, persisted to draft WITHOUT the File and WITHOUT `transcribing` chips (rehydrated error chips can't Retry).

**Why:** the user wanted audio to be a first-class, provenance-preserving attachment like images, not a silent textarea dump. **How to apply:** any future composer attachment work (video, documents, etc.) should follow this same chip + floating-panel + labeled-block-on-send pattern; reuse the JsonPayload Copy button for any "copy full text" affordance.

Critical correctness gaps flagged to dev: (1) removing a chip mid-transcription must truly abort via AbortController, not just hide it; (2) `transcribeAudio` needs signal support added in api.ts.
