import { useEffect, useRef, useState } from "react";

import type { ChatMessage, Citation, ContextBreakdown, TraceItem, TurnUsage } from "./api";
import { TranscriptAudio } from "./AudioChips";
import { approxTokens, ContextComposition } from "./ContextComposition";
import { TranscriptDocuments } from "./DocumentChips";
import { TranscriptImages } from "./ImageChips";
import { Markdown } from "./Markdown";
import { MessageDetails } from "./MessageDetails";
import { ReadAloudButton } from "./ReadAloudButton";

// Color code (project convention): green ok, amber warn, red destructive, muted neutral.
const GREEN = "#1a7f37";
const AMBER = "#b06f00";
const RED = "#b00020";
const MUTED = "#6b7280";

/** Two-rectangles copy glyph (mirrors ImageChips' CopyIcon — monochrome SVG, not emoji). */
function CopyIcon(): React.ReactElement {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" />
    </svg>
  );
}

/** Check-mark glyph shown briefly after a successful copy (matches ImageChips' CheckIcon). */
function CheckIcon(): React.ReactElement {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 13l4 4L19 7" />
    </svg>
  );
}

/** Pencil glyph for Edit (monochrome SVG, same 24-viewBox stroke envelope as CopyIcon). */
function EditIcon(): React.ReactElement {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
    </svg>
  );
}

/** Trash glyph for Delete (monochrome SVG; rendered red at rest — the only destructive control). */
function TrashIcon(): React.ReactElement {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 6h18" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
    </svg>
  );
}

/**
 * The text shown in a user bubble (#426): the original typed prompt (`displayContent`) for new turns,
 * falling back to the folded `content` for old turns that predate the display-vs-model split. A new
 * attachments-only turn has an empty `displayContent` -> render no bubble text (just the chip strip).
 */
const bubbleText = (m: ChatMessage): string => (m.displayContent != null ? m.displayContent : m.content);

/**
 * Whether a user turn carries the structural attachment data (#426). New turns take the structural
 * path (prompt-only bubble + chips); old folded turns (no `displayContent`/`images`/`documents`/
 * `audio`) render `content` verbatim, exactly as before — no retro-parsing of fold markers.
 */
const hasStructured = (m: ChatMessage): boolean =>
  m.displayContent != null ||
  (m.images?.length ?? 0) > 0 ||
  (m.documents?.length ?? 0) > 0 ||
  (m.audio?.length ?? 0) > 0;

/** Whether a user turn has any re-attachable structured resource (#441 Copy fidelity check). */
const hasResources = (m: ChatMessage): boolean =>
  (m.images?.length ?? 0) > 0 || (m.documents?.length ?? 0) > 0 || (m.audio?.length ?? 0) > 0;

/** First line of a question, clipped to ~80 chars with a trailing ellipsis, for the collapsed preview. */
const previewQuestion = (text: string): string => {
  const firstLine = text.split("\n", 1)[0];
  return firstLine.length > 80 ? `${firstLine.slice(0, 80)}…` : firstLine;
};

const fmtMs = (ms: number): string =>
  ms < 1000
    ? `${Math.round(ms)} ms`
    : ms < 60000
      ? `${(ms / 1000).toFixed(1)} s`
      : `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
// Compact in the dense footer (6.0k at >=10k); the full split is in the hover title.
const compactTok = (n: number): string => (n >= 10000 ? `${(n / 1000).toFixed(1)}k` : n.toLocaleString());

/** A subtle per-turn metrics footer under an assistant message: tokens + time, full split on hover. */
function UsageFooter({ usage }: { usage?: TurnUsage }): React.ReactElement | null {
  if (!usage || (usage.total_tokens == null && usage.elapsed_ms == null)) return null;
  const title =
    `${usage.prompt_tokens ?? "?"} prompt + ${usage.completion_tokens ?? "?"} reply ` +
    `= ${usage.total_tokens ?? "?"} tokens` +
    (usage.elapsed_ms != null ? ` in ${fmtMs(usage.elapsed_ms)}` : "");
  return (
    <div data-testid="msg-usage" title={title} style={{ fontSize: "0.7rem", color: "#999", marginTop: 2 }}>
      {usage.total_tokens != null && <>{compactTok(usage.total_tokens)} tok</>}
      {usage.total_tokens != null && usage.elapsed_ms != null && " · "}
      {usage.elapsed_ms != null && <>{fmtMs(usage.elapsed_ms)}</>}
    </div>
  );
}

/**
 * The "Generation stopped." marker under a partial assistant bubble (#412). User-initiated halt, so
 * it is the project warn hue (amber), NOT the red `**Error:**` style — the user must be able to tell
 * "I stopped this" apart from "this broke". Shown when the turn was stopped (live `stopped` flag, or
 * the persisted `meta.stopped` on reload). When no answer text streamed, the copy notes that.
 */
function StoppedMarker({ hasAnswer }: { hasAnswer: boolean }): React.ReactElement {
  return (
    <div
      data-testid="stopped-marker"
      role="note"
      style={{
        marginTop: "0.4rem",
        paddingTop: "0.35rem",
        borderTop: `1px solid ${AMBER}`,
        color: AMBER,
        fontSize: "0.8rem",
      }}
    >
      {hasAnswer ? "Generation stopped." : "Generation stopped before an answer was produced."}
    </div>
  );
}

/**
 * A compact, collapsed-by-default disclosure under a past assistant message showing the per-question
 * context snapshot ("what was in the context window"). Reuses the live meter's composition UI.
 */
function MessageContext({ context, idPrefix }: { context: ContextBreakdown; idPrefix: string }):
  React.ReactElement | null {
  if (!context.items.length) return null;
  return (
    <details data-testid="msg-context" style={{ fontSize: "0.7rem", color: "#6b7280", marginTop: 2 }}>
      <summary style={{ cursor: "pointer" }}>
        Context (~{approxTokens(context.total_chars).toLocaleString()} tokens)
      </summary>
      <div style={{ marginTop: 3 }}>
        <ContextComposition context={context} collapsible={false} idPrefix={idPrefix} />
      </div>
    </details>
  );
}

/** Square icon button used by the per-question Copy/Edit/Delete action row. */
function IconButton({
  testid,
  label,
  color,
  onClick,
  disabled,
  children,
}: {
  testid: string;
  label: string;
  color: string;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <button
      type="button"
      data-testid={testid}
      onClick={onClick}
      disabled={disabled}
      aria-disabled={disabled}
      aria-label={label}
      title={disabled ? "Wait for the current answer to finish." : label}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: "1.7em",
        height: "1.7em",
        background: "none",
        border: "1px solid rgba(127,127,127,0.3)",
        borderRadius: 5,
        color: disabled ? "#bbb" : color,
        cursor: disabled ? "not-allowed" : "pointer",
        padding: 0,
        flexShrink: 0,
      }}
      // A click inside the bubble's action row must not toggle the question collapse or close a
      // sibling chip panel — keep the event local.
      onMouseDown={(e) => e.stopPropagation()}
    >
      {children}
    </button>
  );
}

/** What a user turn carries so the composer can be rehydrated by Copy (#441). */
export interface CopyPayload {
  text: string;
  images: string[];
  imageDescriptions: string[];
  documents: { name: string; text: string }[];
  audio: { name: string; transcript: string }[];
  /** A turn with no structured arrays (old, pre-#426) can only re-attach text. */
  textOnly: boolean;
}

interface UserBubbleProps {
  m: ChatMessage;
  index: number;
  laterTurns: number; // user+assistant turns after this one (drives destructive-warning copy)
  collapsed: boolean;
  busy: boolean;
  onToggle: () => void;
  onCopyToComposer?: (payload: CopyPayload) => void;
  onEditResubmit?: (fromMessageId: number, text: string) => void;
  onDelete?: (fromMessageId: number) => void;
}

/**
 * A user-question bubble (#441) with a hover/focus-revealed Copy / Edit / Delete action row, plus the
 * inline edit-in-place flow and the inline delete confirm. The row is ALWAYS in the DOM (so it is
 * keyboard-reachable and screen-reader-visible) and is shown on hover, `:focus-within`, and always on
 * touch/coarse pointers. All controls are disabled while the chat is `busy` (editing/truncating
 * mid-stream would race the active generation — #412's Stop is how you halt instead).
 */
function UserBubble({
  m,
  index,
  laterTurns,
  collapsed,
  busy,
  onToggle,
  onCopyToComposer,
  onEditResubmit,
  onDelete,
}: UserBubbleProps): React.ReactElement {
  const [hovered, setHovered] = useState(false);
  const [focusWithin, setFocusWithin] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(bubbleText(m));
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [copied, setCopied] = useState(false);
  const [announce, setAnnounce] = useState("");
  const cancelBtnRef = useRef<HTMLButtonElement>(null);

  // Edit/Delete need a stable backend id; the in-flight optimistic turn has none -> those are off.
  const canMutate = m.id != null && !busy;
  const isLatest = laterTurns === 0;
  // The action row is revealed on hover/focus; on touch it has no hover, so a media query keeps it
  // visible. We approximate "no hover" by always rendering it and letting CSS opacity hide it on
  // hover-capable pointers (jsdom has no hover media query, so tests see it via the DOM regardless).
  const rowVisible = hovered || focusWithin;

  function doCopy(): void {
    const textOnly = !hasResources(m);
    const payload: CopyPayload = {
      text: bubbleText(m),
      images: m.images ?? [],
      imageDescriptions: m.image_descriptions ?? [],
      documents: m.documents ?? [],
      audio: m.audio ?? [],
      textOnly,
    };
    onCopyToComposer?.(payload);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
    const count =
      (m.images?.length ?? 0) + (m.documents?.length ?? 0) + (m.audio?.length ?? 0);
    setAnnounce(
      textOnly && bubbleText(m) === "" // nothing meaningful to copy is impossible (always text/res)
        ? "Question copied to clipboard."
        : count > 0
          ? `Question and ${count} attachment(s) loaded into the composer.`
          : "Question loaded into the composer.",
    );
  }

  function startEdit(): void {
    setEditText(bubbleText(m));
    setEditing(true);
    setConfirmingDelete(false);
  }

  function submitEdit(): void {
    if (m.id == null) return;
    const trimmed = editText.trim();
    if (trimmed === "" && !hasResources(m)) return; // empty + no resources -> Resubmit disabled
    setEditing(false);
    onEditResubmit?.(m.id, trimmed);
  }

  function confirmDelete(): void {
    if (m.id == null) return;
    setConfirmingDelete(false);
    onDelete?.(m.id);
    setAnnounce(`Deleted ${laterTurns + 1} turn(s).`);
  }

  // Focus the Cancel button when the delete confirm opens (an accidental Enter cancels). Escape
  // closes the confirm.
  useEffect(() => {
    if (!confirmingDelete) return;
    cancelBtnRef.current?.focus();
    function onKey(e: KeyboardEvent): void {
      if (e.key === "Escape") setConfirmingDelete(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [confirmingDelete]);

  const editEmpty = editText.trim() === "" && !hasResources(m);

  return (
    <div
      data-testid="msg-user"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setFocusWithin(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setFocusWithin(false);
      }}
      // Tint + left accent so each user turn is a clearly delimited block in the transcript.
      style={{
        position: "relative",
        margin: "0.4rem 0",
        background: "#eef3fb",
        color: "#1f2937",
        borderLeft: "3px solid #4a90d9",
        borderRadius: 6,
        padding: "0.5rem 0.6rem",
      }}
    >
      <button
        type="button"
        data-testid="question-toggle"
        aria-expanded={!collapsed}
        aria-label={collapsed ? "Expand question" : "Collapse question"}
        onClick={onToggle}
        style={{
          background: "none",
          border: "none",
          padding: 0,
          marginRight: "0.35rem",
          cursor: "pointer",
          color: "#6b7280",
          fontSize: "0.8rem",
          lineHeight: 1,
        }}
      >
        {collapsed ? "▸" : "▾"}
      </button>
      <strong>You:</strong>{" "}
      {/* Action row, pinned top-right, vertically aligned with the collapse toggle. Always in the
          DOM (keyboard/SR reachable); visually revealed on hover/focus (CSS opacity), always visible
          on touch via @media (hover: none). */}
      <span
        data-testid="question-actions"
        data-revealed={rowVisible ? "true" : "false"}
        style={{
          position: "absolute",
          top: "0.4rem",
          right: "0.5rem",
          display: "inline-flex",
          gap: "0.3rem",
          opacity: rowVisible ? 1 : 0,
          transition: "opacity 0.12s",
        }}
        // Keep the row interactive even when visually hidden, so keyboard focus reveals it.
        className="pai-question-actions"
      >
        <IconButton
          testid={`question-copy-${index}`}
          label={copied ? "Copied" : "Copy question to composer"}
          color={copied ? GREEN : MUTED}
          onClick={doCopy}
        >
          {copied ? <CheckIcon /> : <CopyIcon />}
        </IconButton>
        <IconButton
          testid={`question-edit-${index}`}
          label="Edit question"
          color={MUTED}
          onClick={startEdit}
          disabled={!canMutate}
        >
          <EditIcon />
        </IconButton>
        <IconButton
          testid={`question-delete-${index}`}
          label="Delete question"
          color={RED}
          onClick={() => setConfirmingDelete(true)}
          disabled={!canMutate}
        >
          <TrashIcon />
        </IconButton>
      </span>
      {/* Edit-in-place (#441): the bubble body becomes a textarea seeded with displayContent; the
          resources are carried forward unchanged on resubmit (read-only here). */}
      {editing ? (
        <div data-testid="question-edit-form" style={{ marginTop: "0.35rem" }}>
          <textarea
            data-testid="question-edit-input"
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            rows={3}
            style={{ width: "100%", boxSizing: "border-box", resize: "vertical", font: "inherit", padding: "0.35rem" }}
          />
          {hasStructured(m) && (
            <div data-testid="question-edit-resources" style={{ marginTop: "0.25rem", opacity: 0.85 }}>
              {m.images && m.images.length > 0 && (
                <TranscriptImages images={m.images} descriptions={m.image_descriptions} />
              )}
              {m.documents && m.documents.length > 0 && <TranscriptDocuments documents={m.documents} />}
              {m.audio && m.audio.length > 0 && <TranscriptAudio audio={m.audio} />}
            </div>
          )}
          <div
            data-testid="edit-warning"
            role="note"
            style={{
              marginTop: "0.4rem",
              padding: "0.4rem 0.55rem",
              border: `1px solid ${AMBER}`,
              borderRadius: 4,
              background: "#fff8e1",
              color: AMBER,
              fontSize: "0.82rem",
            }}
          >
            {isLatest
              ? "Re-running this question will replace its current answer."
              : `Resubmitting will delete every later question and answer in this chat and re-run from here. This will discard ${laterTurns} later turn(s).`}
          </div>
          {editEmpty && (
            <p data-testid="edit-empty-hint" style={{ color: AMBER, fontSize: "0.78rem", margin: "0.25rem 0 0" }}>
              Question can&apos;t be empty.
            </p>
          )}
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.4rem", justifyContent: "flex-end" }}>
            <button
              type="button"
              data-testid="edit-resubmit"
              onClick={submitEdit}
              disabled={editEmpty}
              style={{ fontWeight: 600 }}
            >
              Resubmit
            </button>
            <button type="button" data-testid="edit-cancel" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : collapsed ? (
        <span
          style={{
            display: "inline-block",
            maxWidth: "100%",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            verticalAlign: "bottom",
          }}
        >
          {/* The collapsed preview shows the original prompt (#426); old turns clip `content`. */}
          {previewQuestion(bubbleText(m))}
        </span>
      ) : (
        // Expanded: the original typed prompt (#426). An attachments-only turn has empty text
        // (`displayContent === ""`) -> render no bubble line, just the "You:" label + the strip.
        bubbleText(m)
      )}
      {/* Attachment strip (#426), only when expanded and not editing. */}
      {!collapsed && !editing && hasStructured(m) && (
        <>
          {m.images && m.images.length > 0 && (
            <div style={{ marginTop: "0.25rem" }}>
              <TranscriptImages images={m.images} descriptions={m.image_descriptions} />
            </div>
          )}
          {m.documents && m.documents.length > 0 && (
            <div style={{ marginTop: "0.25rem" }}>
              <TranscriptDocuments documents={m.documents} />
            </div>
          )}
          {m.audio && m.audio.length > 0 && (
            <div style={{ marginTop: "0.25rem" }}>
              <TranscriptAudio audio={m.audio} />
            </div>
          )}
        </>
      )}
      {/* Inline delete confirm (#441), anchored to the bubble; Cancel focused, Escape cancels. */}
      {confirmingDelete && (
        <div
          data-testid="delete-confirm"
          role="dialog"
          aria-label="Confirm delete"
          style={{
            marginTop: "0.45rem",
            padding: "0.5rem 0.6rem",
            border: `1px solid ${RED}`,
            borderRadius: 4,
            background: "#fff5f5",
            fontSize: "0.82rem",
          }}
        >
          {isLatest
            ? "Delete this question and its answer? This can't be undone."
            : `Delete this question and everything after it? This removes ${laterTurns} later turn(s) and their answers. This can't be undone.`}
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.4rem", justifyContent: "flex-end" }}>
            <button
              type="button"
              data-testid="delete-confirm-yes"
              onClick={confirmDelete}
              style={{ color: RED, fontWeight: 600 }}
            >
              Delete
            </button>
            <button
              type="button"
              data-testid="delete-confirm-cancel"
              ref={cancelBtnRef}
              onClick={() => setConfirmingDelete(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      {/* SR-only confirmation for Copy / Delete actions. */}
      <span
        data-testid="question-announce"
        aria-live="polite"
        style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)", whiteSpace: "nowrap" }}
      >
        {announce}
      </span>
    </div>
  );
}

interface MessageListProps {
  messages: ChatMessage[];
  trace: Record<number, TraceItem[]>;
  citations: Record<number, Citation[]>;
  busy: boolean;
  ttsEnabled: boolean;
  listRef: React.RefObject<HTMLDivElement | null>;
  onScroll: () => void;
  onAllowHost?: (host: string) => void;
  // Whether the in-flight (last) turn was stopped by the user this session (#412), so the live
  // marker shows even when the partial wasn't reloaded from meta yet.
  liveStopped?: boolean;
  // Per-question actions (#441). Absent in read-only contexts (e.g. unit tests of plain rendering).
  onCopyToComposer?: (payload: CopyPayload) => void;
  onEditResubmit?: (fromMessageId: number, text: string) => void;
  onDelete?: (fromMessageId: number) => void;
  /** Auth token forwarded to Markdown for server-side image localization (#517). */
  token?: string;
}

/** The scrollable transcript: user + assistant messages with reasoning/tool details + citations. */
export function MessageList({
  messages,
  trace,
  citations,
  busy,
  ttsEnabled,
  listRef,
  onScroll,
  onAllowHost,
  liveStopped,
  onCopyToComposer,
  onEditResubmit,
  onDelete,
  token,
}: MessageListProps): React.ReactElement {
  // Per-message collapsed state, keyed by the USER message index. Questions default to expanded.
  const [collapsed, setCollapsed] = useState<Record<number, boolean>>({});

  // An assistant message belongs to the turn opened by its nearest preceding user message. When that
  // user message is explicitly collapsed, fold the whole turn by hiding this assistant message too.
  const isAssistantHidden = (i: number): boolean => {
    for (let j = i - 1; j >= 0; j--) {
      if (messages[j].role === "user") return collapsed[j] === true;
    }
    return false;
  };
  const lastIndex = messages.length - 1;
  return (
    <div
      ref={listRef}
      data-testid="messages"
      onScroll={onScroll}
      style={{
        border: "1px solid #ddd",
        borderRadius: 8,
        padding: "0.75rem",
        flex: 1,
        minHeight: 200,
        overflowY: "auto",
      }}
    >
      {/* Touch / coarse-pointer: the per-question action row has no hover to reveal it, so keep it
          always visible. Desktop hover/focus reveal is handled inline (opacity). */}
      <style>{"@media (hover: none){.pai-question-actions{opacity:1 !important}}"}</style>
      {messages.length === 0 && <p style={{ color: "#888" }}>Ask your local model anything.</p>}
      {messages.map((m, i) =>
        m.role === "assistant" ? (
          isAssistantHidden(i) ? null : (
          <div key={i} data-testid="msg-assistant" style={{ margin: "0.4rem 0", padding: "0 0.6rem" }}>
            <strong>AI:</strong>
            {/* Read aloud (M9.3) — only once the answer has finished streaming and TTS is enabled. */}
            {ttsEnabled && !(busy && i === lastIndex) && (
              <ReadAloudButton text={m.content} />
            )}
            <MessageDetails
              trace={trace[i]?.length ? trace[i] : m.meta?.trace}
              steps={m.meta?.tool_steps}
              thinking={m.meta?.thinking}
              defaultOpen={busy && i === lastIndex}
              onAllowHost={onAllowHost}
            />
            <Markdown content={m.content} streaming={busy && i === lastIndex} token={token} />
            {citations[i]?.length ? (
              <div data-testid="citations" style={{ fontSize: "0.75rem", color: "#555" }}>
                Sources:{" "}
                {citations[i]
                  .map(
                    (c) =>
                      `[${c.n}] ${c.name ?? c.source_id.slice(0, 8)}` +
                      (c.locator ? ` (${c.locator})` : ""),
                  )
                  .join("   ")}
              </div>
            ) : null}
            {/* "Generation stopped." marker (#412): on reload from meta.stopped, or live on the last
                turn the user just stopped. Amber, distinct from the red error path. */}
            {(m.meta?.stopped || (liveStopped && i === lastIndex)) && (
              <StoppedMarker hasAnswer={m.content.trim().length > 0} />
            )}
            <UsageFooter usage={m.meta?.usage} />
            {m.meta?.context && m.meta.context.items.length > 0 && (
              <MessageContext context={m.meta.context} idPrefix={`msg-${i}`} />
            )}
          </div>
          )
        ) : (
          <UserBubble
            key={i}
            m={m}
            index={i}
            // "Later turns" in the destructive copy = later QUESTIONS (user messages after this one);
            // their answers are removed too, but the count the user reasons about is questions.
            laterTurns={messages.slice(i + 1).filter((later) => later.role === "user").length}
            collapsed={collapsed[i] === true}
            busy={busy}
            onToggle={() => setCollapsed((prev) => ({ ...prev, [i]: !prev[i] }))}
            onCopyToComposer={onCopyToComposer}
            onEditResubmit={onEditResubmit}
            onDelete={onDelete}
          />
        ),
      )}
    </div>
  );
}
