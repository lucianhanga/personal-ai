import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { expect, test, vi, beforeEach } from "vitest";

// Mock lazy imports
vi.mock("mermaid", () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn().mockResolvedValue({ svg: "<svg><circle r='5'/></svg>" }),
  },
}));

vi.mock("dompurify", () => ({
  default: {
    sanitize: vi.fn((svg: string) => svg),
  },
}));

// Import AFTER mocks
import { MermaidDiagram } from "./MermaidDiagram";

beforeEach(() => {
  vi.clearAllMocks();
});

test("shows loading state initially", () => {
  render(<MermaidDiagram definition="graph TD\nA-->B" />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
});

test("renders diagram after successful render", async () => {
  render(<MermaidDiagram definition="graph TD\nA-->B" />);
  await waitFor(() => {
    expect(screen.getByLabelText("Mermaid diagram")).toBeInTheDocument();
  });
});

test("calls DOMPurify.sanitize with strict config", async () => {
  const { default: DOMPurify } = await import("dompurify");
  render(<MermaidDiagram definition="graph TD\nA-->B" />);
  await waitFor(() => {
    expect(DOMPurify.sanitize).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        USE_PROFILES: { svg: true, svgFilters: true },
        FORBID_TAGS: expect.arrayContaining(["foreignObject", "script", "style", "iframe", "a"]),
        FORBID_ATTR: expect.arrayContaining(["onload", "onerror", "onclick", "onmouseover", "href", "xlink:href"]),
      })
    );
  });
});

test("shows source+error fallback on render failure", async () => {
  const { default: mermaid } = await import("mermaid");
  (mermaid.render as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("Parse error"));
  render(<MermaidDiagram definition="invalid mermaid @@@@" />);
  await waitFor(() => {
    expect(screen.getByText(/could not be rendered/i)).toBeInTheDocument();
  });
  // Source should be shown
  expect(screen.getByText("invalid mermaid @@@@")).toBeInTheDocument();
});

test("toggle switches between diagram and source", async () => {
  render(<MermaidDiagram definition="graph TD\nA-->B" />);
  await waitFor(() => {
    expect(screen.getByLabelText("Mermaid diagram")).toBeInTheDocument();
  });
  const sourceBtn = screen.getByRole("button", { name: /source/i });
  fireEvent.click(sourceBtn);
  expect(screen.getByRole("button", { name: /source/i })).toHaveAttribute("aria-pressed", "true");
  // diagram hidden, source shown
  expect(screen.queryByLabelText("Mermaid diagram")).toBeNull();
  expect(screen.getByText(/graph TD/)).toBeInTheDocument();
});

test("copy button copies source to clipboard", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  render(<MermaidDiagram definition={"graph TD\nA-->B"} />);
  await waitFor(() => {
    expect(screen.getByLabelText("Mermaid diagram")).toBeInTheDocument();
  });
  const copyBtn = screen.getByRole("button", { name: /copy/i });
  fireEvent.click(copyBtn);
  expect(writeText).toHaveBeenCalledWith("graph TD\nA-->B");
});
