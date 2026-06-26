---
name: attachment-error-ux
description: How attachment upload errors (incl. 413 too-large) surface in PersonalAI chat — per-chip error state, no toast, normalize-once helper
metadata:
  type: project
---

Attachment errors in the chat composer surface **inline on the per-file chip**, never as a toast — there is no toast system to reuse.

**Why:** the file is already a chip, and all three chip families (`DocumentChips.tsx`, `AudioChips.tsx`, `ImageChips.tsx`) already carry a `status: "error"` value + `error?: string` field rendered with the RED token (`#b00020`): red border + red cue text (image chip uses a red overlay badge + `title` tooltip only, so its message is NOT visible inline — needs a caption line for readable errors).

**How to apply:** design new attachment-failure UX as a specialization of the existing `error` status; reuse the RED border + red cue + per-chip `×` (`onRemove(id)`) + the sticky hover/focus panel (open on focus, dismiss on Escape/click-away). The only global error surface is one transient inline line `<p data-testid="chat-error">` above the composer (Chat.tsx) driven by `setError` — reserve it for send/stream failures and send-blocker hints, not per-file errors.

Key gotchas found (2026-06-25):
- `api.ts` upload fns (`uploadFile`/`transcribeAudio`/`describeImage`/`extractDocument`) **discard the response body** and throw `Error("<verb> failed: ${res.status}")`. Friendly mapping is brittle `String(e).includes("413")` in Chat.tsx (`transcribeErrorMessage`/`describeImageError`); docs have no mapper. Recommend a single `normalize413(body, ctx)` parser in api.ts + `humanizeBytes`.
- Backend 413 comes in TWO shapes: body-size middleware `{ok:false,error:{code:"E_TOO_LARGE"}}` (no byte count) and per-endpoint `{detail:"file exceeds <N> bytes"}` (parse N). Limit = `max_upload_bytes`.
- `/api/v1/status` does NOT expose byte limits — adding `max_upload_bytes` there is the clean source for client pre-flight size checks (else a build-constant fallback). Server stays authoritative.
- Send guard (Chat.tsx ~L1053) blocks only in-flight chips; an `error` chip is silently dropped from the `done*` filters on send — that silent drop is the core UX bug. Add `hasRejectedAttachment` to the guard.
- Images are downscaled client-side (`downscaleImage`) before upload, so they rarely hit 413; docs/audio/raw uploads are sent full-size.

Related: [[topbar-composer-conventions]] (no-emoji, color-dot conventions), [[audio-attachment-chips]].
