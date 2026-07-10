import { useEffect, useId, useState, type ReactElement } from "react";

type View = "diagram" | "source";

interface MermaidDiagramProps {
  definition: string;
}

function CopyIcon(): ReactElement {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" />
    </svg>
  );
}

function CheckIcon(): ReactElement {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M5 13l4 4L19 7" />
    </svg>
  );
}

export function MermaidDiagram({ definition }: MermaidDiagramProps): ReactElement {
  const rawId = useId().replace(/:/g, "");
  const diagramId = `mermaid-${rawId}`;

  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [view, setView] = useState<View>("diagram");
  const [copied, setCopied] = useState<boolean>(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    (async () => {
      try {
        const [{ default: mermaid }, { default: DOMPurify }] = await Promise.all([
          import("mermaid"),
          import("dompurify"),
        ]);

        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "base",
          // Render labels as SVG <text>, never HTML in <foreignObject> (which the sanitizer strips —
          // it was the cause of "missing text"). Also closes the HTML-in-label injection vector.
          htmlLabels: false,
          flowchart: { htmlLabels: false },
          themeVariables: {
            background: "#f6f7f9",
            primaryColor: "#e8f5e9",
            primaryBorderColor: "#1a7f37",
            primaryTextColor: "#1a3320",
            lineColor: "#666",
            errorBkgColor: "#ffeeee",
            errorTextColor: "#b00020",
            noteBkgColor: "#fff8e1",
            noteTextColor: "#5a3e00",
          },
        });

        const { svg: renderedSvg } = await mermaid.render(diagramId, definition);
        // Keep Mermaid's own <style> block (DOMPurify sanitizes its CSS) — it carries the edge
        // strokes, text fills, and node/background colors, so forbidding it left the diagram unstyled
        // (black bg, missing edges). Still block the real XSS sinks: script, foreignObject (no HTML
        // labels, see htmlLabels:false), iframe, anchors, and event-handler/href attrs. With
        // securityLevel:"strict" + the pinned mermaid (CVE-2025-54880/54881), this is the safe combo.
        const clean = DOMPurify.sanitize(renderedSvg, {
          USE_PROFILES: { svg: true, svgFilters: true },
          ADD_TAGS: ["style"],
          FORBID_TAGS: ["foreignObject", "script", "iframe", "a"],
          FORBID_ATTR: ["onload", "onerror", "onclick", "onmouseover", "href", "xlink:href"],
        });

        if (!cancelled) {
          setSvg(String(clean));
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(String(err));
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [definition, diagramId]);

  const handleCopy = () => {
    navigator.clipboard.writeText(definition).catch(() => undefined);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  if (loading) {
    return (
      <div className="mermaid-wrapper" aria-busy="true" role="status">
        Rendering diagram...
      </div>
    );
  }

  return (
    <div className="mermaid-wrapper">
      <div className="mermaid-header">
        <div className="mermaid-toggle">
          <button aria-pressed={view === "diagram"} onClick={() => setView("diagram")}>
            Diagram
          </button>
          <button aria-pressed={view === "source"} onClick={() => setView("source")}>
            Source
          </button>
        </div>
        <button className="mermaid-copy-btn" onClick={handleCopy} aria-label="Copy">
          {copied ? <CheckIcon /> : <CopyIcon />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <div>
        {view === "diagram" && svg !== null ? (
          <div
            className="mermaid-svg-output"
            aria-label="Mermaid diagram"
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        ) : view === "diagram" && error !== null ? (
          <>
            <pre>
              <code>{definition}</code>
            </pre>
            <p style={{ color: "#b00020" }}>Diagram could not be rendered: {error}</p>
          </>
        ) : (
          <pre>
            <code>{definition}</code>
          </pre>
        )}
      </div>
    </div>
  );
}
