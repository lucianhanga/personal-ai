import { useEffect, useState } from "react";

import { fetchSettings, saveSettings, type TenantSettings } from "./api";

const OK = "#1a7f37";
const ERR = "#b00";
const WARN = "#b06f00";

// Reject anything that isn't a bare hostname (no scheme, path, or whitespace inside a token).
function badHost(h: string): boolean {
  return /:\/\//.test(h) || h.includes("/") || /\s/.test(h);
}

function parseHosts(csv: string): { hosts: string[]; invalid: string[] } {
  const raw = csv.split(",").map((s) => s.trim()).filter((s) => s !== "");
  const invalid = raw.filter(badHost);
  const hosts = raw.filter((s) => !badHost(s)).map((s) => s.toLowerCase());
  return { hosts, invalid };
}

/** Network egress settings (#290): enable outbound + an allowlist. Security-sensitive, off by default. */
export function Network({ token }: { token: string }): React.ReactElement {
  const [settings, setSettings] = useState<TenantSettings | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [hostsText, setHostsText] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reload(): void {
    fetchSettings(token)
      .then(({ settings, defaults }) => {
        setSettings(settings);
        setEnabled(settings.egress_enabled ?? defaults.egress_enabled);
        setHostsText((settings.allowed_egress_hosts ?? defaults.allowed_egress_hosts).join(", "));
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

  // Enabling outbound is a risk -> require an explicit inline confirm before it commits.
  function onToggle(next: boolean): void {
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

  const { hosts, invalid } = parseHosts(hostsText);

  async function onSave(): Promise<void> {
    if (settings === null) return;
    if (invalid.length > 0) return;
    const next: TenantSettings = {
      ...settings,
      egress_enabled: enabled,
      allowed_egress_hosts: hosts,
    };
    try {
      const stored = await saveSettings(token, next);
      setSettings(stored);
      setDirty(false);
      setSaved(true);
      setError(null);
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  if (settings === null) {
    return (
      <section data-testid="network-panel" aria-label="network">
        {error ? (
          <p data-testid="network-error" style={{ color: ERR }}>
            {error}
          </p>
        ) : (
          <p style={{ color: "#888" }}>Loading…</p>
        )}
      </section>
    );
  }

  // Effective-state line: red when blocked, amber when egress is on (never green — outbound is a risk).
  let stateLine: React.ReactElement;
  if (!enabled) {
    stateLine = (
      <p data-testid="egress-state" style={{ color: ERR, fontSize: "0.82rem" }}>
        Outbound network: BLOCKED (deny all). PersonalAI stays fully local.
      </p>
    );
  } else if (hosts.length === 0) {
    stateLine = (
      <p data-testid="egress-state" style={{ color: WARN, fontSize: "0.82rem" }}>
        Egress is enabled but no hosts are allowed — all outbound requests are still blocked. Add
        hosts to permit them.
      </p>
    );
  } else {
    stateLine = (
      <p data-testid="egress-state" style={{ color: WARN, fontSize: "0.82rem" }}>
        Outbound network permitted to: {hosts.join(", ")}. Only these hosts are reachable.
      </p>
    );
  }

  return (
    <section
      data-testid="network-panel"
      aria-label="network"
      style={{ border: "1px solid #ddd", borderRadius: 8, padding: "0.75rem" }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
        <strong style={{ flex: 1 }}>Network (egress)</strong>
        {dirty && (
          <span data-testid="network-dirty" style={{ color: WARN, fontSize: "0.8rem" }}>
            Unsaved changes
          </span>
        )}
        {saved && !dirty && (
          <span data-testid="network-saved" style={{ color: OK, fontSize: "0.8rem" }}>
            Saved
          </span>
        )}
        <button
          data-testid="network-save"
          onClick={() => void onSave()}
          disabled={!dirty || invalid.length > 0}
        >
          Save
        </button>
      </div>

      {error && (
        <p data-testid="network-error" style={{ color: ERR }}>
          {error}
        </p>
      )}

      <div
        data-testid="egress-risk-note"
        style={{ border: `1px solid ${WARN}`, color: WARN, borderRadius: 6, padding: "0.5rem", fontSize: "0.8rem", margin: "0 0 0.6rem" }}
      >
        Caution: enabling egress lets this app make outbound network requests (for example via tools
        or MCP). Only allow hosts you trust. Leaving this off keeps PersonalAI fully local.
      </div>

      <label style={{ display: "flex", gap: "0.5rem", alignItems: "center", padding: "0.25rem 0" }}>
        <input
          data-testid="egress-enabled-toggle"
          type="checkbox"
          checked={enabled}
          onChange={(e) => onToggle(e.target.checked)}
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

      <label style={{ display: "block", padding: "0.25rem 0" }}>
        <span style={{ fontSize: "0.85rem" }}>Allowed hosts (comma-separated)</span>
        <input
          data-testid="egress-hosts-input"
          style={{ width: "100%", boxSizing: "border-box", marginTop: "0.2rem" }}
          placeholder="e.g. api.example.com, files.example.org"
          value={hostsText}
          disabled={!enabled}
          onChange={(e) => {
            setHostsText(e.target.value);
            touch();
          }}
        />
      </label>
      {!enabled && (
        <p style={{ color: "#888", fontSize: "0.75rem", margin: "0.1rem 0" }}>
          Enable egress to edit the allowlist.
        </p>
      )}
      {invalid.length > 0 && (
        <p data-testid="egress-hosts-error" style={{ color: ERR, fontSize: "0.78rem" }}>
          Enter bare hostnames only (no http://, no paths): {invalid.join(", ")}
        </p>
      )}

      {stateLine}
    </section>
  );
}
