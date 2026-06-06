import { useEffect, useState } from "react";

import { fetchHealth } from "./api";
import { Chat } from "./Chat";

type Status = "loading" | "connected" | "disconnected";

const STATUS_LABEL: Record<Status, string> = {
  loading: "Checking backend...",
  connected: "Backend connected",
  disconnected: "Backend not reachable",
};

const TOKEN_KEY = "personalai_token";

export function App(): React.ReactElement {
  const [status, setStatus] = useState<Status>("loading");
  const [token, setToken] = useState<string>(
    () => localStorage.getItem(TOKEN_KEY) ?? import.meta.env.VITE_API_TOKEN ?? "",
  );

  useEffect(() => {
    let active = true;
    fetchHealth().then((ok) => {
      if (active) setStatus(ok ? "connected" : "disconnected");
    });
    return () => {
      active = false;
    };
  }, []);

  function updateToken(value: string): void {
    setToken(value);
    localStorage.setItem(TOKEN_KEY, value);
  }

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "2rem", maxWidth: 760 }}>
      <h1>PersonalAI</h1>

      <p>
        <strong>Status:</strong>{" "}
        <span data-testid="backend-status" data-status={status}>
          {STATUS_LABEL[status]}
        </span>{" "}
        · <span data-testid="provider-badge">Local</span>
      </p>

      <p style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
        <label htmlFor="token">API token:</label>
        <input
          id="token"
          data-testid="token-input"
          type="password"
          value={token}
          placeholder="PERSONALAI_AUTH_TOKEN"
          onChange={(e) => updateToken(e.target.value)}
        />
      </p>

      {token ? (
        <Chat token={token} />
      ) : (
        <p data-testid="need-token" style={{ color: "#888" }}>
          Enter your backend API token to start chatting.
        </p>
      )}

      <p style={{ color: "#555", fontSize: "0.85rem", marginTop: "1rem" }} data-testid="security-note">
        Local-first: network egress is disabled by default; remote providers are opt-in.
      </p>
    </main>
  );
}
