import { useEffect, useState } from "react";
import { allowEgressHost, localizeImage } from "./api";

// Color convention: amber = pending consent, green = allow, red = deny.
const AMBER = "#b06f00";
const GREEN = "#1a7f37";
const RED = "#b00020";

type State =
  | { phase: "loading" }
  | { phase: "ok"; dataUrl: string }
  | { phase: "approval"; host: string }
  | { phase: "error" };

/**
 * Server-side image localization (#517). Fetches a remote http(s) image through the backend
 * /api/v1/images/localize endpoint so the browser never loads the remote URL directly (no-egress).
 * On success renders the returned data: URL. On needs_approval renders an inline consent card
 * mirroring the tool egress flow. On error renders a safe text link to the original URL.
 */
export function LocalizedImage({
  url,
  alt,
  token,
}: {
  url: string;
  alt?: string;
  token: string;
}): React.ReactElement {
  const [state, setState] = useState<State>({ phase: "loading" });
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setState({ phase: "loading" });
    setDismissed(false);

    void localizeImage(token, url).then((result) => {
      if (cancelled) return;
      if (result.ok && result.data_url) {
        setState({ phase: "ok", dataUrl: result.data_url });
      } else if (result.needs_approval && result.host) {
        setState({ phase: "approval", host: result.host });
      } else {
        setState({ phase: "error" });
      }
    });

    return () => {
      cancelled = true;
    };
  }, [token, url]);

  if (state.phase === "loading") {
    return (
      <span
        data-testid="localized-image-loading"
        aria-busy="true"
        style={{ color: "#888", fontSize: "0.85rem" }}
      >
        Loading image...
      </span>
    );
  }

  if (state.phase === "ok") {
    return (
      <img
        data-testid="localized-image"
        src={state.dataUrl}
        alt={alt}
        loading="lazy"
        style={{ maxWidth: "100%", height: "auto" }}
      />
    );
  }

  if (state.phase === "approval" && !dismissed) {
    const { host } = state;
    return (
      <span
        data-testid="localized-image"
        style={{
          display: "inline-flex",
          flexDirection: "column",
          gap: "0.4rem",
          border: `1px solid ${AMBER}`,
          background: "#fff8e1",
          borderRadius: "0.4rem",
          padding: "0.5rem 0.7rem",
          fontSize: "0.85rem",
          verticalAlign: "top",
        }}
      >
        <span>
          Show image from <strong>{host}</strong>? It will be fetched from that host.
        </span>
        <span style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
          <button
            data-testid="localized-image-approve"
            onClick={() => {
              void allowEgressHost(token, host).then(() =>
                localizeImage(token, url).then((result) => {
                  if (result.ok && result.data_url) {
                    setState({ phase: "ok", dataUrl: result.data_url });
                  } else {
                    setState({ phase: "error" });
                  }
                }),
              );
            }}
            style={{
              border: `1px solid ${GREEN}`,
              background: "#fff",
              color: GREEN,
              borderRadius: "0.3rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
              font: "inherit",
              fontSize: "0.82rem",
              fontWeight: 600,
            }}
          >
            Allow
          </button>
          <button
            data-testid="localized-image-deny"
            onClick={() => setDismissed(true)}
            style={{
              border: `1px solid ${RED}`,
              background: "#fff",
              color: RED,
              borderRadius: "0.3rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
              font: "inherit",
              fontSize: "0.82rem",
              fontWeight: 600,
            }}
          >
            Don't allow
          </button>
        </span>
      </span>
    );
  }

  // error or dismissed approval
  return (
    <a
      data-testid="localized-image-fallback"
      href={url}
      rel="noopener noreferrer"
      target="_blank"
    >
      {alt ?? url}
    </a>
  );
}
