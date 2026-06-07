import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import "./markdown.css";

// Safe by default: react-markdown does NOT render raw HTML (no rehype-raw), so model output like
// <script> or <img onerror> is shown as text, not executed. Links open in a new tab safely.
const components: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
};

export function Markdown({ content }: { content: string }): React.ReactElement {
  return (
    <div className="md" data-testid="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
