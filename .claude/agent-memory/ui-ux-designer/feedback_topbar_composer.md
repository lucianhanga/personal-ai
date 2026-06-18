---
name: topbar-composer-conventions
description: PersonalAI top-bar and composer UX conventions — no token input in local mode, no glyphs, multi-line composer with Enter-to-send
metadata:
  type: feedback
---

Established UX conventions for the PersonalAI chat top bar and composer:

- The bearer "Token" input is meaningless in app_mode=local (no login) — it is legacy clutter and must NOT live in the top bar. Relocate to Settings -> Preferences -> Provider (advanced) for remote/multi-tenant deployments only. In local mode chat must work with an empty token (no `need-token` block).
- The "Local" provider badge is redundant and should be removed; provider/caps text already convey local vs remote.
- Backend status renders as an 8px color dot + label using the shared palette (green #1a7f37 ok, red #b00 error, amber #b06f00 warn). Keep `data-testid="backend-status"` + `data-status`.
- NO emoji or icon-glyphs anywhere, including the accordion toggle triangles (replace with ASCII text affordances like Show/Hide).
- Composer is a 4-line resizable `<textarea>` (testid stays `composer`). Convention: Enter = send, Shift+Enter = newline, Cmd/Ctrl+Enter = send; suppress send while IME `isComposing`. Send disabled when busy || !model || empty/whitespace; label "Sending…" while busy.

**Why:** project rules (no emoji/glyph, color-code instead) + local-first zero-login default; the single-line input and token field were user-flagged clutter.

**How to apply:** apply to any future edits of `apps/ui/src/Chat.tsx` top bar and composer. Pair with [[model-selection-topbar-decision]].
