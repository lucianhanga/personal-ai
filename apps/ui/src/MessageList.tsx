import { useState } from "react";

import type { ChatMessage, Citation, ContextBreakdown, TraceItem, TurnUsage } from "./api";
import { approxTokens, ContextComposition } from "./ContextComposition";
import { Markdown } from "./Markdown";
import { MessageDetails } from "./MessageDetails";
import { ReadAloudButton } from "./ReadAloudButton";

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

interface MessageListProps {
  messages: ChatMessage[];
  trace: Record<number, TraceItem[]>;
  citations: Record<number, Citation[]>;
  busy: boolean;
  ttsEnabled: boolean;
  listRef: React.RefObject<HTMLDivElement | null>;
  onScroll: () => void;
  onAllowHost?: (host: string) => void;
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
}: MessageListProps): React.ReactElement {
  // Per-message collapsed state, keyed by message index. Questions default to expanded.
  const [collapsed, setCollapsed] = useState<Record<number, boolean>>({});
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
      {messages.length === 0 && <p style={{ color: "#888" }}>Ask your local model anything.</p>}
      {messages.map((m, i) =>
        m.role === "assistant" ? (
          <div key={i} data-testid="msg-assistant" style={{ margin: "0.4rem 0", padding: "0 0.6rem" }}>
            <strong>AI:</strong>
            {/* Read aloud (M9.3) — only once the answer has finished streaming and TTS is enabled. */}
            {ttsEnabled && !(busy && i === messages.length - 1) && (
              <ReadAloudButton text={m.content} />
            )}
            <MessageDetails
              trace={trace[i]?.length ? trace[i] : m.meta?.trace}
              steps={m.meta?.tool_steps}
              thinking={m.meta?.thinking}
              defaultOpen={busy && i === messages.length - 1}
              onAllowHost={onAllowHost}
            />
            <Markdown content={m.content} />
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
            <UsageFooter usage={m.meta?.usage} />
            {m.meta?.context && m.meta.context.items.length > 0 && (
              <MessageContext context={m.meta.context} idPrefix={`msg-${i}`} />
            )}
          </div>
        ) : (
          <div
            key={i}
            data-testid="msg-user"
            // Tint + left accent so each user turn is a clearly delimited block in the transcript.
            style={{
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
              aria-expanded={!collapsed[i]}
              aria-label={collapsed[i] ? "Expand question" : "Collapse question"}
              onClick={() => setCollapsed((prev) => ({ ...prev, [i]: !prev[i] }))}
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
              {collapsed[i] ? "▸" : "▾"}
            </button>
            <strong>You:</strong>{" "}
            {collapsed[i] ? (
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
                {previewQuestion(m.content)}
              </span>
            ) : (
              m.content
            )}
            {!collapsed[i] && m.images && m.images.length > 0 && (
              <div data-testid="msg-images" style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", marginTop: "0.25rem" }}>
                {m.images.map((src, k) => (
                  <img
                    key={k}
                    src={src}
                    alt="attachment"
                    style={{ maxHeight: 160, borderRadius: 4, border: "1px solid #ddd" }}
                  />
                ))}
              </div>
            )}
          </div>
        ),
      )}
    </div>
  );
}
