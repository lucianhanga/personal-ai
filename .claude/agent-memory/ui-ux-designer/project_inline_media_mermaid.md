---
name: inline-media-mermaid
description: UX spec for rendering inline images + Mermaid diagrams in assistant/user chat messages (#507 + mermaid)
metadata:
  type: project
---

Feature: render markdown images inline and ```mermaid fenced blocks as diagrams inside chat messages (assistant + user). Relates to backlog #507.

**Why:** Assistant markdown images and mermaid fences currently show as raw text/links; users expect rendered media. Project is local-first / fail-closed / no-egress.

**How to apply (key design decisions):**
- All rendering goes through `apps/ui/src/Markdown.tsx` component overrides (`img`, and `code`/`pre` for mermaid). react-markdown v9, NO rehype-raw (raw HTML stays inert) — keep it that way; do not add rehype-raw.
- Remote-URL images (http/https) must be gated behind an explicit per-host allow click (no-egress); data:/blob: render immediately. Mirror the host-allow pattern already used via `onAllowHost` in MessageList/MessageDetails.
- Reuse ImageChips.tsx patterns: GREEN #1a7f37 / AMBER #b06f00 / RED #b00020 / ACCENT #4a90d9 / MUTED #6b7280; DescriptionPanel + ImageGrid lightbox/zoom analog; alt text from markdown alt (assistant) and image_descriptions (attachments).
- Mermaid: render diagram with source/code toggle + copy-source; on parse failure show the source fenced block (never crash). Theme must match app light theme + green=ok/amber=warn/red=error.
- Streaming: do NOT render a mermaid block until its closing ``` fence arrives (count fences / detect unclosed). Partial fence renders as a code block placeholder, not a broken diagram. Applies to the in-flight last assistant turn (busy && i===lastIndex in MessageList).
- New testids proposed: `md-image`, `md-image-remote-gate`, `mermaid`, `mermaid-diagram`, `mermaid-source`, `mermaid-toggle`, `mermaid-copy`, `mermaid-error`. Existing reused: `markdown`, `image-panel`/`msg-images` conventions.

See [[project_panels_redesign]] for tool-I/O progressive-disclosure pattern reused by the source/code toggle.
