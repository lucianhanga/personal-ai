import { useState } from "react";

import { JsonPayload } from "./JsonPayload";

const TOOL = "#7c3aed"; // violet — matches the trace's tool hue
const OK = "#1a7f37"; // green
const ERR = "#b00020"; // red
const WARN = "#b06f00"; // amber
// Muted text a user must READ uses #6b7280 (AA); #888/#999 stay decorative.
const READABLE = "#6b7280";

/** A compact one-line hint for the args: the first string value (clipped) or an "(N args)" count. */
function argHint(args: unknown): string {
  if (args == null || typeof args !== "object") return typeof args === "string" ? clipStr(args) : "";
  const entries = Object.entries(args as Record<string, unknown>);
  if (entries.length === 0) return "";
  const firstStr = entries.find(([, v]) => typeof v === "string" && v.length > 0);
  if (firstStr) return clipStr(String(firstStr[1]));
  return `(${entries.length} arg${entries.length > 1 ? "s" : ""})`;
}

function clipStr(s: string): string {
  return s.length > 60 ? `${s.slice(0, 60)}…` : s;
}

/** The Tier-1 status pill: green ok / red error / grey no result / amber pending. */
function StatusPill({ ok, hasResult }: { ok?: boolean; hasResult: boolean }): React.ReactElement {
  let color: string;
  let bg: string;
  let text: string;
  if (!hasResult) {
    // No tool_result paired yet: pending while the turn streams, "no result" once it settles.
    color = READABLE;
    bg = "rgba(127,127,127,0.12)";
    text = "no result";
  } else if (ok) {
    color = OK;
    bg = "rgba(26,127,55,0.12)";
    text = "ok";
  } else {
    color = ERR;
    bg = "rgba(176,0,32,0.10)";
    text = "error";
  }
  return (
    <span
      data-testid="toolio-status"
      style={{ color, background: bg, borderRadius: 8, padding: "0 0.4rem", fontSize: "0.72rem", fontWeight: 600 }}
    >
      {text}
    </span>
  );
}

/**
 * One tool interaction (a tool_call paired with its optional tool_result) shown as progressive
 * disclosure: Tier 1 is a single clickable summary line; Tier 2 (collapsed) reveals the request +
 * response JSON. Preserves the egress allow-on-deny affordance when a result was blocked.
 */
export function ToolIO({
  tool,
  args,
  ok,
  output,
  error,
  host,
  allowed,
  onAllow,
}: {
  tool: string;
  args?: unknown;
  ok?: boolean;
  output?: unknown;
  error?: string | null;
  // The egress host an error was blocked on (null when not a block); plus its allow-on-deny wiring.
  host?: string | null;
  allowed?: boolean;
  onAllow?: () => void;
}): React.ReactElement {
  // Collapsed by default, EXCEPT when there's a pending egress block the user must act on — then
  // open so the Allow affordance is immediately visible (it lives in Tier 2).
  const [open, setOpen] = useState<boolean>(Boolean(host && onAllow && !allowed));
  const hasResult = ok != null || output != null || error != null;
  const hint = argHint(args);

  return (
    <div data-testid="toolio" style={{ background: "#f6f0fe", borderRadius: 3, padding: "1px 5px", margin: "1px 0" }}>
      {/* Tier 1: always-visible summary; clicking toggles Tier 2. */}
      <button
        data-testid="toolio-summary"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.4rem",
          width: "100%",
          background: "none",
          border: "none",
          cursor: "pointer",
          padding: "1px 0",
          textAlign: "left",
          font: "inherit",
          // Keep the whole summary on ONE line; the args hint truncates with an ellipsis when long.
          whiteSpace: "nowrap",
          overflow: "hidden",
        }}
      >
        <span style={{ color: READABLE, fontSize: "0.72rem", flexShrink: 0 }}>{open ? "▾" : "▸"}</span>
        <span style={{ color: TOOL, fontWeight: 600, flexShrink: 0 }}>Tool</span>
        <span style={{ color: "#1f2937", flexShrink: 0 }}>{tool}</span>
        {hint && (
          <span
            style={{
              color: READABLE,
              fontStyle: "italic",
              minWidth: 0,
              flex: "0 1 auto",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {hint}
          </span>
        )}
        <span style={{ marginLeft: "auto", flexShrink: 0 }}>
          <StatusPill ok={ok} hasResult={hasResult} />
        </span>
      </button>

      {/* Tier 2: request + response, collapsed by default. */}
      {open && (
        <div data-testid="toolio-detail" style={{ paddingLeft: "0.9rem", paddingBottom: "0.25rem" }}>
          <JsonPayload label="Request" value={args ?? {}} />
          {hasResult &&
            (ok === false || error ? (
              <div data-testid="toolio-error" style={{ color: ERR, fontSize: "0.78rem", margin: "2px 0", whiteSpace: "pre-wrap" }}>
                {error ?? "error"}
              </div>
            ) : output != null ? (
              <JsonPayload label="Response" value={output} />
            ) : (
              <div style={{ color: OK, fontSize: "0.78rem", margin: "2px 0" }}>ok</div>
            ))}
          {/* Egress allow-on-deny: re-offer outbound access to the host the blocked tool reached. */}
          {host &&
            onAllow &&
            (allowed ? (
              <span data-testid="egress-allowed" style={{ color: OK, fontSize: "0.78rem" }}>
                allowed {host}; re-send to use it.
              </span>
            ) : (
              <span style={{ color: READABLE, fontSize: "0.78rem" }}>
                allow outbound to <strong>{host}</strong> from now on?{" "}
                <button data-testid="egress-allow-btn" onClick={onAllow} style={{ color: WARN }}>
                  Allow
                </button>
              </span>
            ))}
        </div>
      )}
    </div>
  );
}
