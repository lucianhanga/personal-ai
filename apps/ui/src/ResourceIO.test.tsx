import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";

import { ResourceIO, resourceLabel } from "./ResourceIO";

// --- resourceLabel (the Tier-1 verb map, #424) ---------------------------------------------------

test("resourceLabel maps each action to its verb + ref", () => {
  expect(resourceLabel("image_described", "cat.jpg")).toBe("Described image — cat.jpg");
  expect(resourceLabel("document_extracted", "notes.pdf")).toBe("Extracted document — notes.pdf");
  expect(resourceLabel("audio_transcribed", "call.m4a")).toBe("Transcribed audio — call.m4a");
});

// --- Tier-1 summary line -------------------------------------------------------------------------

test("renders a collapsed summary: 'Resource' + the action label + a status pill, detail hidden", () => {
  render(
    <ResourceIO action="image_described" refName="cat.jpg" state="done" model="vision:7b" ms={120} />,
  );
  const node = screen.getByTestId("timeline-resource");
  expect(node).toHaveAttribute("data-status", "done");
  const summary = screen.getByTestId("resourceio-summary");
  expect(summary).toHaveAttribute("aria-expanded", "false");
  expect(summary).toHaveTextContent("Resource");
  expect(summary).toHaveTextContent("Described image — cat.jpg");
  expect(screen.getByTestId("resourceio-status")).toHaveTextContent("done");
  // Tier 2 is collapsed by default.
  expect(screen.queryByTestId("resourceio-detail")).toBeNull();
});

test("the status pill renders words (never color-only) for each state", () => {
  const { rerender } = render(<ResourceIO action="image_described" refName="x" state="in-progress" />);
  expect(screen.getByTestId("resourceio-status")).toHaveTextContent("in progress");
  rerender(<ResourceIO action="image_described" refName="x" state="done" />);
  expect(screen.getByTestId("resourceio-status")).toHaveTextContent("done");
  rerender(<ResourceIO action="image_described" refName="x" state="error" />);
  expect(screen.getByTestId("resourceio-status")).toHaveTextContent("error");
});

// --- Tier-2 disclosure ---------------------------------------------------------------------------

test("expanding shows model, duration, and the ref when a model + ms are present", () => {
  render(
    <ResourceIO action="audio_transcribed" refName="call.m4a" state="done" model="whisper-1" ms={2400} />,
  );
  fireEvent.click(screen.getByTestId("resourceio-summary"));
  const detail = screen.getByTestId("resourceio-detail");
  expect(screen.getByTestId("resourceio-summary")).toHaveAttribute("aria-expanded", "true");
  expect(detail).toHaveTextContent("Model: whisper-1");
  expect(detail).toHaveTextContent("Duration: 2.4 s"); // ms >= 1000 -> seconds, 1 decimal
  expect(detail).toHaveTextContent("Resource: call.m4a");
});

test("a document extract has no model -> shows the ref + duration but no Model line", () => {
  render(<ResourceIO action="document_extracted" refName="notes.pdf" state="done" model={null} ms={45} />);
  fireEvent.click(screen.getByTestId("resourceio-summary"));
  const detail = screen.getByTestId("resourceio-detail");
  expect(detail).not.toHaveTextContent("Model:");
  expect(detail).toHaveTextContent("Duration: 45 ms"); // ms < 1000 -> milliseconds
  expect(detail).toHaveTextContent("Resource: notes.pdf");
});

test("an in-progress node with no model yet shows a 'working…' placeholder", () => {
  render(<ResourceIO action="image_described" refName="cat.jpg" state="in-progress" />);
  fireEvent.click(screen.getByTestId("resourceio-summary"));
  expect(screen.getByTestId("resourceio-detail")).toHaveTextContent("working…");
});

test("an error node surfaces the error message in red detail; ok node has none", () => {
  const { rerender } = render(
    <ResourceIO
      action="image_described"
      refName="cat.jpg"
      state="error"
      error="vision model unavailable"
    />,
  );
  fireEvent.click(screen.getByTestId("resourceio-summary"));
  expect(screen.getByTestId("resourceio-error")).toHaveTextContent("vision model unavailable");

  // A done node with no error renders no error block.
  rerender(<ResourceIO action="image_described" refName="cat.jpg" state="done" ms={10} />);
  expect(within(screen.getByTestId("resourceio-detail")).queryByTestId("resourceio-error")).toBeNull();
});

test("duration formats minutes for long runs", () => {
  render(<ResourceIO action="audio_transcribed" refName="long.m4a" state="done" model="whisper-1" ms={125000} />);
  fireEvent.click(screen.getByTestId("resourceio-summary"));
  expect(screen.getByTestId("resourceio-detail")).toHaveTextContent("Duration: 2m 5s");
});
