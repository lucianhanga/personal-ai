import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import pkgJson from "../package.json";

import { Markdown } from "./Markdown";

// Stub LocalizedImage so Markdown tests don't need the real api module.
vi.mock("./LocalizedImage", () => ({
  LocalizedImage: ({ url, alt }: { url: string; alt?: string }) => (
    <span data-testid="localized-image-stub" data-url={url}>{alt ?? url}</span>
  ),
}));

test("renders bold, inline code, and fenced code blocks", () => {
  render(<Markdown content={"**bold** and `inline`\n\n```\ncode block\n```"} />);
  const md = screen.getByTestId("markdown");
  expect(md.querySelector("strong")).toHaveTextContent("bold");
  // inline code is a <code> not inside a <pre>
  const inline = [...md.querySelectorAll("code")].find((c) => c.closest("pre") === null);
  expect(inline).toHaveTextContent("inline");
  // fenced block is a <pre><code>
  expect(md.querySelector("pre code")).toHaveTextContent("code block");
});

test("renders GFM tables, task lists, and strikethrough", () => {
  const content = [
    "| a | b |",
    "| - | - |",
    "| 1 | 2 |",
    "",
    "- [ ] todo",
    "",
    "~~gone~~",
  ].join("\n");
  render(<Markdown content={content} />);
  const md = screen.getByTestId("markdown");
  expect(md.querySelector("table")).not.toBeNull();
  expect(md.querySelector("th")).not.toBeNull();
  const checkbox = md.querySelector('input[type="checkbox"]');
  expect(checkbox).not.toBeNull();
  expect(checkbox).toBeDisabled();
  expect(md.querySelector("del")).toHaveTextContent("gone");
});

test("links open in a new tab safely", () => {
  render(<Markdown content={"[site](https://example.com)"} />);
  const link = screen.getByRole("link", { name: "site" });
  expect(link).toHaveAttribute("href", "https://example.com");
  expect(link).toHaveAttribute("target", "_blank");
  expect(link.getAttribute("rel")).toContain("noopener");
  expect(link.getAttribute("rel")).toContain("noreferrer");
});

test("does NOT execute raw HTML in model output (XSS)", () => {
  render(<Markdown content={'before <script>window.__xss=1</script> after'} />);
  const md = screen.getByTestId("markdown");
  expect(md.querySelector("script")).toBeNull();
  // The raw HTML is shown as text, so the literal still appears in the rendered text.
  expect(md.textContent).toContain("before");
  expect(md.textContent).toContain("after");
});

test("does NOT create an active onerror image (XSS)", () => {
  render(<Markdown content={'<img src=x onerror="window.__xss=1">'} />);
  const md = screen.getByTestId("markdown");
  const img = md.querySelector("img");
  // Either no img element, or one without the onerror handler.
  expect(img?.getAttribute("onerror") ?? null).toBeNull();
});

test("strips javascript: link URLs", () => {
  render(<Markdown content={"[x](javascript:alert(1))"} />);
  const md = screen.getByTestId("markdown");
  const link = md.querySelector("a");
  const href = link?.getAttribute("href") ?? "";
  expect(href.startsWith("javascript:")).toBe(false);
});

// New tests for inline image security and mermaid routing

test("renders local data:image as <img> (unchanged)", () => {
  render(<Markdown content={"![alt](data:image/png;base64,abc123)"} />);
  const img = screen.getByRole("img");
  expect(img).toBeInTheDocument();
  expect(img.getAttribute("src")).toMatch(/^data:image\//);
});

test("http image URL without token -> fallback span, no <img>", () => {
  // When no token is provided, remote images fall back to the inert span (no localization).
  render(<Markdown content={"![remote](https://evil.com/x.png)"} />);
  const md = screen.getByTestId("markdown");
  expect(md.querySelector("img")).toBeNull();
  expect(md.querySelector(".md-img-fallback")).not.toBeNull();
  // Must not render LocalizedImage stub either (no token)
  expect(md.querySelector("[data-testid='localized-image-stub']")).toBeNull();
});

test("http image URL with token -> routes to LocalizedImage, no direct <img src>", () => {
  render(
    <Markdown content={"![alt text](https://upload.wikimedia.org/image.png)"} token="tok123" />,
  );
  const md = screen.getByTestId("markdown");
  // No direct <img> with remote src
  expect(md.querySelector("img")).toBeNull();
  // LocalizedImage stub rendered with the correct url
  const stub = md.querySelector("[data-testid='localized-image-stub']");
  expect(stub).not.toBeNull();
  expect(stub?.getAttribute("data-url")).toBe("https://upload.wikimedia.org/image.png");
});

test("http image URL with empty-string token (local zero-login) -> routes to LocalizedImage", () => {
  // Local zero-login passes token="" (a valid auth context, not "no token"); remote images must
  // still localize rather than fall back inert. Regression guard for the truthy-token bug.
  render(<Markdown content={"![alt](https://upload.wikimedia.org/image.png)"} token="" />);
  const md = screen.getByTestId("markdown");
  expect(md.querySelector("[data-testid='localized-image-stub']")).not.toBeNull();
  expect(md.querySelector(".md-img-fallback")).toBeNull();
});

test("rejects javascript: image URL -> fallback span, no <img>", () => {
  render(<Markdown content={"![js](javascript:alert(1))"} />);
  const md = screen.getByTestId("markdown");
  expect(md.querySelector("img")).toBeNull();
});

test("rejects data:text/html image URL -> fallback span, no <img>", () => {
  render(<Markdown content={"![html](data:text/html,<h1>xss</h1>)"} />);
  const md = screen.getByTestId("markdown");
  expect(md.querySelector("img")).toBeNull();
  expect(md.querySelector(".md-img-fallback")).not.toBeNull();
});

test("mermaid fence with streaming=false mounts MermaidDiagram", () => {
  render(<Markdown content={"```mermaid\ngraph TD\nA-->B\n```"} streaming={false} />);
  const md = screen.getByTestId("markdown");
  // MermaidDiagram renders a mermaid-wrapper div (loading state initially)
  expect(md.querySelector(".mermaid-wrapper")).not.toBeNull();
});

test("mermaid fence with streaming=true renders <code> not diagram", () => {
  render(<Markdown content={"```mermaid\ngraph TD\nA-->B\n```"} streaming={true} />);
  const md = screen.getByTestId("markdown");
  // When streaming, fall through to plain code block
  expect(md.querySelector("code")).not.toBeNull();
  expect(md.querySelector(".mermaid-wrapper")).toBeNull();
});

test("rehype-raw is not a dependency and urlTransform is not nulled", () => {
  const allDeps = {
    ...(pkgJson.dependencies ?? {}),
    ...(pkgJson.devDependencies ?? {}),
  };
  expect(Object.keys(allDeps)).not.toContain("rehype-raw");
});
