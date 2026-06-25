---
name: personalai-audio-chips
description: Audio attachment UX in apps/ui — drag-drop-only transcription chips, send-folding, no summarize (#406 revised #389)
metadata:
  type: project
---

Audio transcription UX in `apps/ui` (Chat composer). Revised in #406 from #389.

**Current model (#406):** Audio is added by DRAG-DROP ONLY onto `composer-dropzone` (no file-picker button, no `<input type=file>`). Each dropped `audio/*` file becomes a chip in `audioAttachments` state (`{id,name,status,transcript,error?}`, statuses `transcribing|done|empty|error`). Transcription runs in the BACKGROUND per chip with a per-chip `AbortController` (in `audioAbortRef` Map) — removing a chip mid-flight aborts its fetch. Chips render via `AudioChips.tsx` (separate component): `done` chips are focusable and reveal a floating transcript panel (`audio-panel`, role=dialog) on hover/focus/click with a Copy button (JsonPayload copy pattern). Testids: `audio-attachment` (with `data-status`), `remove-audio-${id}`, `copy-audio-${id}`, `audio-panel`.

**Send-flow (Option b):** `send()` folds each `done` chip into message CONTENT as `\n\n[Audio: ${name}]\n${transcript}` appended after typed text (images still ride `message.images`). Send is disabled while ANY chip is `transcribing`; allowed when there's a `done` transcript even with empty text. Chips clear on successful send. Draft persistence (sessionStorage `personalai_composer_draft`) saves `done` chips' transcripts only (restored as `done`), never File/in-flight/AbortController.

**Removed in #406:** the `♪` `audio-file-btn` + `audio-file-input`, the global `summarize-send` button + `sendSummarize()`, and the single-file `audio-progress`/`audioFileName`/`audioNotice` line. `send()` no longer takes an `override` arg.

**api.ts:** `transcribeAudio(token, audio, filename?, signal?)` forwards `signal` to fetch (back-compatible; mic caller omits it).

**Why/how to apply:** mic flow (toggleRecording -> composer + auto-send) is UNCHANGED and separate from the file/chip flow. If touching audio, keep chips for files vs composer-insert for mic. Color code: green #1a7f37, amber #b06f00, red #b00020, accent #4a90d9, muted #6b7280; glyph `♪` not emoji.
