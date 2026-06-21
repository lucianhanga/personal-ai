import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { ReadAloudButton } from "./ReadAloudButton";

afterEach(() => vi.restoreAllMocks());

interface FakeUtterance {
  text: string;
  onend: (() => void) | null;
  onerror: (() => void) | null;
}

function stubSpeech(): { speak: ReturnType<typeof vi.fn>; cancel: ReturnType<typeof vi.fn> } {
  const synth = { speak: vi.fn(), cancel: vi.fn() };
  vi.stubGlobal("speechSynthesis", synth);
  vi.stubGlobal(
    "SpeechSynthesisUtterance",
    class {
      text: string;
      onend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(text: string) {
        this.text = text;
      }
    } as unknown as typeof SpeechSynthesisUtterance,
  );
  return synth;
}

test("speaks the answer, then stops on a second click (M9.3)", () => {
  const synth = stubSpeech();
  render(<ReadAloudButton text="hello world" />);

  const btn = screen.getByTestId("read-aloud");
  expect(btn).toHaveAttribute("aria-label", "Read answer aloud");

  fireEvent.click(btn);
  expect(synth.speak).toHaveBeenCalledTimes(1);
  const utt = synth.speak.mock.calls[0][0] as FakeUtterance;
  expect(utt.text).toBe("hello world");
  expect(btn).toHaveAttribute("aria-label", "Stop reading");

  // Second click stops.
  fireEvent.click(btn);
  expect(synth.cancel).toHaveBeenCalled();
  expect(btn).toHaveAttribute("aria-label", "Read answer aloud");
});

test("resets to idle when speech ends on its own", () => {
  const synth = stubSpeech();
  render(<ReadAloudButton text="done soon" />);
  fireEvent.click(screen.getByTestId("read-aloud"));
  const utt = synth.speak.mock.calls[0][0] as FakeUtterance;
  act(() => utt.onend?.());
  expect(screen.getByTestId("read-aloud")).toHaveAttribute("aria-label", "Read answer aloud");
});

test("renders nothing without speech support or for empty text", () => {
  vi.stubGlobal("speechSynthesis", undefined);
  const { container: a } = render(<ReadAloudButton text="anything" />);
  expect(a.querySelector('[data-testid="read-aloud"]')).toBeNull();

  stubSpeech();
  const { container: b } = render(<ReadAloudButton text="   " />);
  expect(b.querySelector('[data-testid="read-aloud"]')).toBeNull();
});
