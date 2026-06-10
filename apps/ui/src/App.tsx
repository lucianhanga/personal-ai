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

// Keep the bearer token in sessionStorage (cleared when the tab closes, not shared across tabs)
// rather than localStorage, to shrink the window an XSS bug could exfiltrate it. Migrate any token
// left in localStorage by older builds, then remove the persistent copy.
export function readToken(): string {
  const fromSession = sessionStorage.getItem(TOKEN_KEY);
  if (fromSession) return fromSession;
  const legacy = localStorage.getItem(TOKEN_KEY);
  if (legacy) {
    sessionStorage.setItem(TOKEN_KEY, legacy);
    localStorage.removeItem(TOKEN_KEY);
    return legacy;
  }
  return import.meta.env.VITE_API_TOKEN ?? "";
}

export function App(): React.ReactElement {
  const [status, setStatus] = useState<Status>("loading");
  const [token, setToken] = useState<string>(readToken);

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
    sessionStorage.setItem(TOKEN_KEY, value);
    localStorage.removeItem(TOKEN_KEY); // never keep a persistent copy
  }

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "1rem", height: "100vh", boxSizing: "border-box" }}>
      <Chat
        token={token}
        status={status}
        statusLabel={STATUS_LABEL[status]}
        onToken={updateToken}
      />
    </main>
  );
}
