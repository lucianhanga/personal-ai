---
name: personalai-sent-message-attachments
description: How sent-message attachments render (display-vs-model split) + the camel/snake wire gotcha in apps/ui
metadata:
  type: project
---

Sent user turns use a **display-vs-model split** (#426, PR #430). `ChatMessage.content` is the folded model-facing string (typed + `[Audio:]`/`[Image:]`/`[Document:]` blocks) the model receives; the bubble renders `displayContent` (original typed prompt) + structured `documents:[{name,text}]` / `audio:[{name,transcript}]` / `images`+`image_descriptions`. `MessageList` picks the structural path via `hasStructured(m)` (any of displayContent/images/documents/audio present); old folded turns lack all of them and render `content` verbatim — there is NO retro-parsing of fold markers.

Read-only transcript chip components mirror the composer ones but with NO remove control and `data-status="sent"`: `TranscriptImages` (ImageChips.tsx), `TranscriptDocuments` (DocumentChips.tsx), `TranscriptAudio` (AudioChips.tsx). They reuse the composer's `TextPanel`/`TranscriptPanel`/`DescriptionPanel` (sticky open on hover/focus/click, dismiss on Escape/click-away, `role="dialog"`, SVG copy). Composer chips and transcript chips share `data-testid` (`document-attachment`/`audio-attachment`/`image-attachment`) — distinguish in tests by `data-status` (composer: small/large/done/describing; transcript: `sent`).

**Wire-format gotcha (camelCase vs snake_case):** the UI `ChatMessage` type mixes conventions — `image_descriptions` is snake (passes through untouched) but `displayContent` is camel and the backend `ChatMessageIn` expects `display_content`. So `streamChat` (api.ts) maps `displayContent -> display_content` on send, and `fetchConversation` maps `display_content -> displayContent` on read-back. `documents`/`audio` are single words and pass through both ways. If you add another camelCase request field, you MUST add the same two mappings or it silently won't reach/return from the backend.

**Backend persist boundary:** `_sanitize_display_content` + `_sanitize_attachments` in `apps/backend/.../app.py` mirror `_sanitize_activities` — allowlist fields only, bounded count (`_MAX_ATTACHMENTS_PER_TURN`), length caps. Persist writes to the user-turn `meta` in the same block as `meta["images"]` (the #396 "this turn's last user message only" rule); `get_conversation` surfaces them top-level. All additive + migration-free.
