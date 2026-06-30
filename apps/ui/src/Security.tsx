import { useEffect, useState } from "react";

import {
  fetchSettings,
  saveSettings,
  type TenantSettings,
  type TenantSettingsDefaults,
} from "./api";

const OK = "#1a7f37";
const ERR = "#b00";
const WARN = "#b06f00";
// Security accent — the section is flagged red in the nav; the panel echoes it.
const SEC = "#b00020";

// A valid DNS hostname: dot-separated labels (letters/digits/hyphen, no edge hyphen), a real TLD,
// total length <= 253. Used to flag each allow-list entity as valid (tick) or not (x).
const DNS_RE = /^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$/i;
function isValidDns(h: string): boolean {
  return DNS_RE.test(h);
}
// Split a typed value (comma- or whitespace-separated) into normalized host tokens.
function splitHosts(raw: string): string[] {
  return raw
    .split(/[,\s]+/)
    .map((s) => s.trim().toLowerCase())
    .filter((s) => s !== "");
}

interface ApprovalSpec {
  key: "tool_approval_required" | "agent_human_gate" | "agent_egress_gate";
  testid: string;
  label: string;
  help: string;
}

// The three human-in-the-loop checkpoints, in rough order of how often they fire.
const APPROVALS: ApprovalSpec[] = [
  {
    key: "tool_approval_required",
    testid: "security-tool-approval",
    label: "Require approval for high-risk tools",
    help: "HIGH-risk tools (reaching the network, running code, writing files) do not execute until you approve them for that turn. This sets the default for the composer's “approve tools” switch.",
  },
  {
    key: "agent_human_gate",
    testid: "security-answer-gate",
    label: "Pause each turn to approve the answer",
    help: "In multi-agent mode, each turn suspends after drafting so you can approve or reject the proposed answer before it is shown. Requires the multi-agent graph.",
  },
  {
    key: "agent_egress_gate",
    testid: "security-egress-gate",
    label: "Pause to allow or deny new network hosts",
    help: "When a tool tries to reach a host that is not allow-listed below, the turn pauses for an allow/deny choice and resumes automatically once you allow it. Works in both single- and multi-agent mode.",
  },
];

const CARD: React.CSSProperties = {
  border: "1px solid #e2e2e2",
  borderRadius: 6,
  margin: "0 0 0.6rem",
  padding: "0.6rem",
};

/** Security settings: human-in-the-loop approval gates + network egress. All security-sensitive and
 *  conservative by default. Consolidates the approval gates (moved out of Agents) and the former
 *  Network panel into one place. */
export function Security({ token }: { token: string }): React.ReactElement {
  const [settings, setSettings] = useState<TenantSettings | null>(null);
  const [defaults, setDefaults] = useState<TenantSettingsDefaults | null>(null);
  const [enabled, setEnabled] = useState(false); // egress on/off (tracked apart from the draft)
  const [hosts, setHosts] = useState<string[]>([]); // allow-list entities
  const [hostInput, setHostInput] = useState(""); // the "add a host" field
  const [confirming, setConfirming] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reload(): void {
    fetchSettings(token)
      .then(({ settings, defaults }) => {
        setSettings(settings);
        setDefaults(defaults);
        setEnabled(settings.egress_enabled ?? defaults.egress_enabled);
        setHosts([...(settings.allowed_egress_hosts ?? defaults.allowed_egress_hosts)]);
        setHostInput("");
        setError(null);
        setDirty(false);
        setSaved(false);
        setConfirming(false);
      })
      .catch((e: unknown) => setError(String(e)));
  }

  useEffect(reload, [token]);

  function touch(): void {
    setDirty(true);
    setSaved(false);
  }

  function setApproval(key: ApprovalSpec["key"], value: boolean): void {
    if (settings === null) return;
    setSettings({ ...settings, [key]: value });
    touch();
  }

  // Enabling outbound is a risk -> require an explicit inline confirm before it commits.
  function onToggleEgress(next: boolean): void {
    if (next) {
      setConfirming(true);
    } else {
      setEnabled(false);
      setConfirming(false);
      touch();
    }
  }

  function confirmEnable(): void {
    setEnabled(true);
    setConfirming(false);
    touch();
  }

  // Add the typed host(s) as allow-list entities (dedup, normalized); invalid-DNS entries are still
  // added so they show with an x marker and can be corrected/removed (Save stays blocked until clean).
  function addHosts(): void {
    const tokens = splitHosts(hostInput);
    if (tokens.length === 0) return;
    setHosts((prev) => [...prev, ...tokens.filter((t) => !prev.includes(t))]);
    setHostInput("");
    touch();
  }

  function removeHost(h: string): void {
    setHosts((prev) => prev.filter((x) => x !== h));
    touch();
  }

  const invalid = hosts.filter((h) => !isValidDns(h));

  async function onSave(): Promise<void> {
    if (settings === null) return;
    if (invalid.length > 0) return;
    const next: TenantSettings = { ...settings, egress_enabled: enabled, allowed_egress_hosts: hosts };
    try {
      const stored = await saveSettings(token, next);
      setSettings(stored);
      setEnabled(stored.egress_enabled ?? defaults!.egress_enabled);
      setHosts([...(stored.allowed_egress_hosts ?? defaults!.allowed_egress_hosts)]);
      setDirty(false);
      setSaved(true);
      setError(null);
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  if (settings === null || defaults === null) {
    return (
      <section data-testid="security-panel" aria-label="security">
        {error ? (
          <p data-testid="security-error" style={{ color: ERR }}>
            {error}
          </p>
        ) : (
          <p style={{ color: "#888" }}>Loading…</p>
        )}
      </section>
    );
  }

  // Effective-state line for egress: red when blocked, amber when on (never green — outbound is risk).
  let stateLine: React.ReactElement;
  if (!enabled) {
    stateLine = (
      <p data-testid="egress-state" style={{ color: ERR, fontSize: "0.82rem", margin: "0.3rem 0 0" }}>
        Outbound network: BLOCKED (deny all). PersonalAI stays fully local.
      </p>
    );
  } else if (hosts.length === 0) {
    stateLine = (
      <p data-testid="egress-state" style={{ color: WARN, fontSize: "0.82rem", margin: "0.3rem 0 0" }}>
        Egress is enabled but no hosts are allowed — all outbound requests are still blocked. Add
        hosts to permit them.
      </p>
    );
  } else {
    stateLine = (
      <p data-testid="egress-state" style={{ color: WARN, fontSize: "0.82rem", margin: "0.3rem 0 0" }}>
        Outbound network permitted to: {hosts.join(", ")}. Only these hosts are reachable.
      </p>
    );
  }

  return (
    <section
      data-testid="security-panel"
      aria-label="security"
      style={{ border: `1px solid ${SEC}`, borderTop: `3px solid ${SEC}`, borderRadius: 8, padding: "0.75rem" }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
        <strong style={{ flex: 1, color: SEC }}>Security</strong>
        {dirty && (
          <span data-testid="security-dirty" style={{ color: WARN, fontSize: "0.8rem" }}>
            Unsaved changes
          </span>
        )}
        {saved && !dirty && (
          <span data-testid="security-saved" style={{ color: OK, fontSize: "0.8rem" }}>
            Saved
          </span>
        )}
        <button data-testid="security-save" onClick={() => void onSave()} disabled={!dirty || invalid.length > 0}>
          Save
        </button>
      </div>

      {error && (
        <p data-testid="security-error" style={{ color: ERR }}>
          {error}
        </p>
      )}

      {/* Approvals — human-in-the-loop checkpoints. */}
      <fieldset data-testid="security-approvals" style={CARD}>
        <legend style={{ fontSize: "0.8rem", color: SEC }}>Approvals</legend>
        <p style={{ color: "#777", fontSize: "0.72rem", margin: "0 0 0.5rem" }}>
          Human-in-the-loop checkpoints — each makes the system stop and wait for you before doing
          something sensitive. All off by default.
        </p>
        {APPROVALS.map((a) => (
          <label key={a.key} style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start", padding: "0.3rem 0" }}>
            <input
              data-testid={a.testid}
              type="checkbox"
              checked={settings[a.key] ?? defaults[a.key]}
              onChange={(e) => setApproval(a.key, e.target.checked)}
              style={{ marginTop: "0.2rem" }}
            />
            <span style={{ fontSize: "0.82rem" }}>
              <span style={{ fontWeight: 600 }}>{a.label}</span>
              <br />
              <span style={{ color: "#777", fontSize: "0.74rem" }}>{a.help}</span>
            </span>
          </label>
        ))}
        {!(settings.agent_egress_gate ?? defaults.agent_egress_gate) && (
          <p
            data-testid="security-egress-gate-warning"
            style={{ color: WARN, fontSize: "0.74rem", margin: "0.2rem 0 0", paddingLeft: "1.4rem" }}
          >
            Heads up: with the network-host gate off, a tool that needs a host you have not
            allow-listed below will <strong>fail that call</strong> (you will get an Allow button to
            permit the host, then re-send) instead of pausing in-turn for your decision.
          </p>
        )}
      </fieldset>

      {/* Network egress — relocated from the former Network panel. */}
      <fieldset data-testid="security-network" style={CARD}>
        <legend style={{ fontSize: "0.8rem", color: SEC }}>Network egress</legend>
        <p style={{ color: "#777", fontSize: "0.72rem", margin: "0 0 0.5rem" }}>
          Outbound network access for in-process tools and MCP servers. Off by default — PersonalAI
          stays fully local. When on, only the hosts you allow-list are reachable.
        </p>

        <div
          data-testid="egress-risk-note"
          style={{ border: `1px solid ${WARN}`, color: WARN, borderRadius: 6, padding: "0.5rem", fontSize: "0.78rem", margin: "0 0 0.5rem" }}
        >
          Caution: enabling egress lets this app make outbound network requests (for example via tools
          or MCP). Only allow hosts you trust.
        </div>

        <label style={{ display: "flex", gap: "0.5rem", alignItems: "center", padding: "0.25rem 0" }}>
          <input
            data-testid="egress-enabled-toggle"
            type="checkbox"
            checked={enabled}
            onChange={(e) => onToggleEgress(e.target.checked)}
          />
          <span style={{ fontSize: "0.85rem" }}>Allow outbound network (egress)</span>
        </label>

        {confirming && (
          <div
            data-testid="egress-confirm"
            style={{ border: `1px solid ${WARN}`, color: WARN, borderRadius: 6, padding: "0.5rem", fontSize: "0.82rem", margin: "0.25rem 0" }}
          >
            Enable outbound network? This opens external requests.{" "}
            <button data-testid="egress-confirm-yes" onClick={confirmEnable}>
              Enable
            </button>{" "}
            <button data-testid="egress-confirm-no" onClick={() => setConfirming(false)}>
              Cancel
            </button>
          </div>
        )}

        <div style={{ fontSize: "0.82rem", marginTop: "0.4rem" }}>
          Allowed hosts
          {/* Add field: Enter or comma commits; accepts several at once. */}
          <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.2rem" }}>
            <input
              data-testid="egress-hosts-input"
              type="text"
              value={hostInput}
              placeholder="add a host, e.g. api.example.com"
              onChange={(e) => setHostInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === ",") {
                  e.preventDefault();
                  addHosts();
                }
              }}
              style={{ flex: 1, boxSizing: "border-box" }}
            />
            <button data-testid="egress-hosts-add" type="button" onClick={addHosts} disabled={splitHosts(hostInput).length === 0}>
              Add
            </button>
          </div>

          {/* Entities: one chip per host, a tick when it is a valid DNS name (x otherwise), and a
              remove button. Min-height keeps the area open even when empty. */}
          <div
            data-testid="egress-hosts"
            style={{ display: "flex", flexWrap: "wrap", alignContent: "flex-start", gap: "0.35rem", minHeight: "4.5rem", marginTop: "0.35rem", padding: "0.4rem", border: "1px solid #e2e2e2", borderRadius: 6, background: "#fafafa" }}
          >
            {hosts.length === 0 && (
              <span style={{ color: "#999", fontSize: "0.78rem" }}>No hosts allowed yet.</span>
            )}
            {hosts.map((h) => {
              const ok = isValidDns(h);
              return (
                <span
                  key={h}
                  data-testid={`egress-host-${h}`}
                  title={ok ? "valid hostname" : "not a valid DNS hostname"}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.3rem",
                    padding: "0.15rem 0.4rem",
                    borderRadius: 12,
                    fontSize: "0.78rem",
                    border: `1px solid ${ok ? "#bfe3c6" : "#f0b3b3"}`,
                    background: ok ? "#eef7f0" : "#fdeaea",
                    color: ok ? "#1a7f37" : ERR,
                  }}
                >
                  <span aria-hidden="true">{ok ? "✓" : "✗"}</span>
                  <span style={{ color: "#222" }}>{h}</span>
                  <button
                    data-testid={`egress-host-remove-${h}`}
                    type="button"
                    aria-label={`Remove ${h}`}
                    onClick={() => removeHost(h)}
                    style={{ border: "none", background: "none", cursor: "pointer", color: "#888", fontSize: "0.9rem", lineHeight: 1, padding: 0 }}
                  >
                    {"×"}
                  </button>
                </span>
              );
            })}
          </div>
        </div>
        {invalid.length > 0 && (
          <p data-testid="egress-hosts-invalid" style={{ color: ERR, fontSize: "0.78rem", margin: "0.25rem 0 0" }}>
            {invalid.length} host{invalid.length > 1 ? "s are" : " is"} not a valid DNS name — fix or
            remove {invalid.length > 1 ? "them" : "it"} before saving.
          </p>
        )}
        {stateLine}
      </fieldset>
    </section>
  );
}
