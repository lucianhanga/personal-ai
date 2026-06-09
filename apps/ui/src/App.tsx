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
