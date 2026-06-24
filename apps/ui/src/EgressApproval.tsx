import { useState } from "react";

import { JsonPayload } from "./JsonPayload";

// Color code (consistent with the rest of the UI): amber = caution/allow-once, green = allow+remember,
// red = block, blue = informational.
const AMBER = "#b06f00";
const GREEN = "#1a7f37";
const RED = "#b00020";
const BLUE = "#4a90d9";
// Muted text a user must READ uses #6b7280 (AA).
const READABLE = "#6b7280";

export type EgressDecision = "egress_allow_once" | "egress_allow_always" | "egress_deny";

// Arg keys whose VALUE could carry a credential or session token; case-insensitive. We deep-redact
// matching values before showing the outbound payload so the "More info" panel never leaks secrets.
const SECRET_KEY = /^(authorization|auth|token|secret|api[_-]?key|password|cookie|set-cookie|bearer)$/i;
const REDACTED = "<redacted>";

/** Deep-copy `value`, replacing the value of any secret-looking key (at any depth) with "<redacted>". */
export function redactSecrets(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redactSecrets);
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = SECRET_KEY.test(k) ? REDACTED : redactSecrets(v);
    }
    return out;
  }
  return value;
}

/** One decision button: a glyph icon + visible label, with a descriptive `title` tooltip. */
function ActionButton({
  testid,
  glyph,
  label,
  title,
  color,
  busy,
  onClick,
}: {
  testid: string;
  glyph: string;
  label: string;
  title: string;
  color: string;
  busy?: boolean;
  onClick: () => void;
}): React.ReactElement {
  return (
    <button
      data-testid={testid}
      title={title}
      onClick={onClick}
      disabled={busy}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "0.35rem",
        background: "#fff",
        border: `1px solid ${color}`,
        borderRadius: "0.3rem",
        color,
        cursor: busy ? "default" : "pointer",
        font: "inherit",
        fontSize: "0.85rem",
        fontWeight: 600,
        padding: "0.3rem 0.6rem",
        opacity: busy ? 0.6 : 1,
      }}
    >
      <span aria-hidden="true" style={{ fontSize: "1rem", lineHeight: 1 }}>
        {glyph}
      </span>
      {label}
    </button>
  );
}

/**
 * The blocking egress-approval gate (#377): a tool wants to reach a non-allowlisted host and the run
 * has durably paused. The user allows once, allows + remembers (adds to the allowlist), or denies.
 * "More info" reveals the exact outbound request (args, secrets redacted) before deciding.
 */
export function EgressApproval({
  host,
  tool,
  args,
  onResolve,
  busy,
}: {
  host: string;
  tool?: string;
  args?: Record<string, unknown>;
  onResolve: (decision: EgressDecision) => void;
  busy?: boolean;
}): React.ReactElement {
  const [showDetails, setShowDetails] = useState(false);

  const allowOnce = (
    <ActionButton
      testid="egress-allow-once"
      glyph="⟳"
      label="Allow once"
      title="Allow this request for this run only; don't remember it."
      color={AMBER}
      busy={busy}
      onClick={() => onResolve("egress_allow_once")}
    />
  );
  const allowAlways = (
    <ActionButton
      testid="egress-allow-always"
      glyph="✓"
      label="Allow always"
      title="Allow and remember this host for next time (added to your allowlist)."
      color={GREEN}
      busy={busy}
      onClick={() => onResolve("egress_allow_always")}
    />
  );
  const deny = (
    <ActionButton
      testid="egress-deny"
      glyph="✕"
      label="Don't allow"
      title="Block this request; the tool returns an error and the run continues."
      color={RED}
      busy={busy}
      onClick={() => onResolve("egress_deny")}
    />
  );

  return (
    <div
      data-testid="egress-approval"
      style={{
        border: `1px solid ${AMBER}`,
        background: "#fff8e1",
        borderRadius: "0.4rem",
        padding: "0.6rem 0.8rem",
        fontSize: "0.85rem",
      }}
    >
      <p style={{ margin: "0 0 0.5rem" }}>
        This answer needs to reach <strong data-testid="egress-host">{host}</strong>
        {tool ? <> (via {tool})</> : null}.
      </p>

      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        {allowOnce}
        {allowAlways}
        {deny}
        <ActionButton
          testid="egress-more-info"
          glyph="ⓘ"
          label="More info"
          title="See exactly what would be sent to this host before deciding."
          color={BLUE}
          onClick={() => setShowDetails((s) => !s)}
        />
      </div>

      {showDetails && (
        <div
          data-testid="egress-details"
          style={{
            marginTop: "0.6rem",
            paddingTop: "0.5rem",
            borderTop: "1px solid rgba(176,111,0,0.3)",
          }}
        >
          <p style={{ margin: "0 0 0.35rem", color: READABLE }}>
            Outbound request to <strong style={{ color: AMBER }}>{host}</strong>
            {tool ? <> via {tool}</> : null}:
          </p>
          <JsonPayload label="Args" value={redactSecrets(args ?? {})} />
          <p style={{ margin: "0.4rem 0 0.5rem", color: READABLE, fontSize: "0.8rem" }}>
            Only allow hosts you trust — a permitted host can receive data on future calls too.
          </p>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {allowOnce}
            {allowAlways}
            {deny}
          </div>
        </div>
      )}
    </div>
  );
}
