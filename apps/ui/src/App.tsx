import { useEffect, useState } from "react";

import { fetchHealth } from "./api";

type Status = "loading" | "connected" | "disconnected";

const STATUS_LABEL: Record<Status, string> = {
  loading: "Checking backend...",
  connected: "Backend connected",
  disconnected: "Backend not reachable",
};

export function App(): React.ReactElement {
  const [status, setStatus] = useState<Status>("loading");

  useEffect(() => {
    let active = true;
    fetchHealth().then((ok) => {
      if (active) setStatus(ok ? "connected" : "disconnected");
    });
    return () => {
      active = false;
    };
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "2rem", maxWidth: 640 }}>
      <h1>PersonalAI</h1>
      <p>Local-first, omni-capable AI assistant.</p>

      <section aria-label="status">
        <p>
          <strong>Status:</strong>{" "}
          <span data-testid="backend-status" data-status={status}>
            {STATUS_LABEL[status]}
          </span>
        </p>
        <p>
          <strong>Provider:</strong>{" "}
          <span data-testid="provider-badge" data-kind="local">
            Local
          </span>
        </p>
      </section>

      <p style={{ color: "#555", fontSize: "0.9rem" }} data-testid="security-note">
        Local-first: network egress is disabled by default; remote providers are opt-in.
      </p>
    </main>
  );
}
