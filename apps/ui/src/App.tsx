import { useCallback, useEffect, useState } from "react";

import { fetchHealth, fetchSession, logout, type SessionInfo } from "./api";
import { Chat } from "./Chat";
import { Login } from "./Login";

// Session resolution: "loading" until the first /session/me; null = unauthenticated (hosted, show
// Login); a SessionInfo = authed (dev/cookie/token); "error" = backend unreachable, so render the
// app anyway (it shows a disconnected badge) rather than trapping the user behind a login wall.
type SessionState = "loading" | "error" | null | SessionInfo;

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
  const [session, setSession] = useState<SessionState>("loading");

  const refreshSession = useCallback(() => {
    setSession("loading");
    fetchSession(token).then(
      (s) => setSession(s),
      () => setSession("error"), // backend unreachable -> render the app, not a login wall
    );
  }, [token]);

  useEffect(() => {
    let active = true;
    fetchHealth().then((ok) => {
      if (active) setStatus(ok ? "connected" : "disconnected");
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(refreshSession, [refreshSession]);

  function updateToken(value: string): void {
    setToken(value);
    sessionStorage.setItem(TOKEN_KEY, value);
    localStorage.removeItem(TOKEN_KEY); // never keep a persistent copy
  }

  const wrap = (child: React.ReactElement): React.ReactElement => (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "1rem", height: "100vh", boxSizing: "border-box" }}>
      {child}
    </main>
  );

  if (session === "loading") return wrap(<p data-testid="session-loading">Loading...</p>);
  if (session === null) return wrap(<Login onAuthed={refreshSession} />);

  async function signOut(): Promise<void> {
    await logout(token);
    refreshSession(); // -> 401 in hosted mode -> back to Login
  }

  // Offer sign-out only for real (cookie) logins; dev/token sessions have nothing to sign out of.
  const canSignOut = session !== "error" && session.auth_kind === "cookie";
  return wrap(
    <>
      {canSignOut && (
        <button
          data-testid="logout"
          type="button"
          onClick={signOut}
          style={{ position: "fixed", top: 8, right: 8, zIndex: 10, padding: "4px 10px" }}
        >
          Sign out
        </button>
      )}
      <Chat token={token} status={status} statusLabel={STATUS_LABEL[status]} onToken={updateToken} />
    </>,
  );
}
