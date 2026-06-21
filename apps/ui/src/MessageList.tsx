import type { ChatMessage, Citation, TraceItem } from "./api";
import { Markdown } from "./Markdown";
import { MessageDetails } from "./MessageDetails";

interface MessageListProps {
  messages: ChatMessage[];
  trace: Record<number, TraceItem[]>;
  citations: Record<number, Citation[]>;
  busy: boolean;
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
  listRef,
  onScroll,
  onAllowHost,
}: MessageListProps): React.ReactElement {
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
          <div key={i} data-testid="msg-assistant" style={{ margin: "0.4rem 0" }}>
            <strong>AI:</strong>
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
          </div>
        ) : (
          <p key={i} data-testid="msg-user" style={{ margin: "0.4rem 0" }}>
            <strong>You:</strong> {m.content}
          </p>
        ),
      )}
    </div>
  );
}
