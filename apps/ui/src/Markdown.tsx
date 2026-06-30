import { isValidElement, useMemo, useState, type ReactElement, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { MermaidDiagram } from "./MermaidDiagram";
import "./markdown.css";

// Safe by default: react-markdown does NOT render raw HTML (no rehype-raw), so model output like
// <script> or <img onerror> is shown as text, not executed. Links open in a new tab safely.

// Allowed URL protocols (same set as react-markdown's built-in default safe list).
const SAFE_PROTOCOLS = new Set(["http", "https", "irc", "ircs", "mailto", "xmpp"]);

// Custom URL transform: extends react-markdown's default to additionally pass data:image/ and
// blob: URLs through for inline image rendering. javascript:, vbscript:, data:text/html, and
// other dangerous schemes are still blocked. Do NOT set urlTransform={null} (that disables ALL
// sanitization and allows javascript: hrefs through).
function safeUrlTransform(url: string): string {
  if (url.startsWith("data:image/")) return url;
  if (url.startsWith("blob:")) return url;
  // Replicate the react-markdown default safe-URI algorithm.
  const colon = url.indexOf(":");
  const slash = url.indexOf("/");
  const question = url.indexOf("?");
  const hash = url.indexOf("#");
  if (
    colon < 0 ||
    (slash > -1 && colon > slash) ||
    (question > -1 && colon > question) ||
    (hash > -1 && colon > hash) ||
    SAFE_PROTOCOLS.has(url.slice(0, colon))
  ) {
    return url;
  }
  return "";
}

// SafeImage: allow inline images only for data:image/, blob:, or same-origin/relative URLs.
// Any http(s), javascript:, data:text/html, or other scheme renders an inert fallback span.
function SafeImage({ src, alt }: { src?: string; alt?: string }): ReactElement {
  const [showFallback, setShowFallback] = useState(false);

  const isAllowed = (() => {
    if (!src) return false;
    if (src.startsWith("data:image/")) return true;
    if (src.startsWith("blob:")) return true;
    if (src.startsWith("/") || src.startsWith("./") || src.startsWith("../")) return true;
    if (!src.includes(":")) return true; // no scheme -> relative path
    return false;
  })();

  if (!isAllowed || showFallback) {
    return <span className="md-img-fallback">{alt ?? src}</span>;
  }

  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      style={{ maxWidth: "100%", height: "auto" }}
      onError={() => setShowFallback(true)}
    />
  );
}

function makeComponents(streaming: boolean): Components {
  return {
    a: ({ href, children }) => (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    ),
    img: ({ src, alt }) => <SafeImage src={src} alt={alt} />,
    pre: ({ children }) => {
      // Inspect direct code-element child to detect fenced mermaid blocks.
      const codeEl = isValidElement(children)
        ? (children as ReactElement<{ className?: string; children?: ReactNode }>)
        : null;
      const isMermaid = codeEl?.props?.className?.includes("language-mermaid") ?? false;
      if (isMermaid) {
        const def = String(codeEl?.props?.children ?? "").trimEnd();
        if (streaming) {
          // While streaming, render as plain code block to avoid partial-parse failures.
          return (
            <pre>
              <code className={codeEl?.props?.className}>{def}</code>
            </pre>
          );
        }
        return <MermaidDiagram definition={def} />;
      }
      return <pre>{children}</pre>;
    },
  };
}

export function Markdown({
  content,
  streaming = false,
}: {
  content: string;
  streaming?: boolean;
}): ReactElement {
  const components = useMemo(() => makeComponents(streaming), [streaming]);
  return (
    <div className="md" data-testid="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={components}
        urlTransform={safeUrlTransform}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
