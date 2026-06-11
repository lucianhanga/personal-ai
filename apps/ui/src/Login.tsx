import { useState } from "react";

import { login, signup } from "./api";

/** Email + password login / signup for hosted mode. Shown when the session resolves to 401. */
export function Login({ onAuthed }: { onAuthed: () => void }): React.ReactElement {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mode === "signup") await signup(email, password);
      await login(email, password);
      onAuthed();
    } catch {
      setError(
        mode === "signup" ? "Could not create the account." : "Invalid email or password.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ maxWidth: 360, margin: "10vh auto", fontFamily: "system-ui, sans-serif" }}>
      <h1 style={{ fontSize: "1.4rem" }}>PersonalAI</h1>
      <p style={{ color: "#666", marginTop: 0 }}>
        {mode === "signup" ? "Create your account" : "Sign in to continue"}
      </p>
      <form onSubmit={submit} data-testid="login-form">
        <label style={{ display: "block", marginBottom: 8 }}>
          Email
          <input
            data-testid="login-email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            style={{ width: "100%", padding: 8, boxSizing: "border-box" }}
          />
        </label>
        <label style={{ display: "block", marginBottom: 8 }}>
          Password
          <input
            data-testid="login-password"
            type="password"
            autoComplete={mode === "signup" ? "new-password" : "current-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            style={{ width: "100%", padding: 8, boxSizing: "border-box" }}
          />
        </label>
        {error && (
          <p data-testid="login-error" style={{ color: "#c0392b" }} role="alert">
            {error}
          </p>
        )}
        <button data-testid="login-submit" type="submit" disabled={busy} style={{ width: "100%", padding: 8 }}>
          {busy ? "..." : mode === "signup" ? "Create account" : "Sign in"}
        </button>
      </form>
      <button
        data-testid="login-toggle"
        type="button"
        onClick={() => {
          setMode(mode === "login" ? "signup" : "login");
          setError("");
        }}
        style={{ marginTop: 12, background: "none", border: "none", color: "#2980b9", cursor: "pointer" }}
      >
        {mode === "login" ? "Need an account? Sign up" : "Have an account? Sign in"}
      </button>
    </div>
  );
}
