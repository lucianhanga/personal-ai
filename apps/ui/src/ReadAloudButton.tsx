import { useEffect, useState } from "react";

// Read assistant answers aloud (M9.3, slice 1) using the browser's built-in speech synthesis —
// fully client-side, zero-setup, no backend audio pipeline. Monochrome non-emoji glyphs match the
// composer's voice controls: play triangle = read, square = stop. A later slice adds a server-side
// Piper provider for consistent neural voices.

function speechSupported(): boolean {
  return typeof window !== "undefined" && window.speechSynthesis != null;
}

export function ReadAloudButton({ text }: { text: string }): React.ReactElement | null {
  const [speaking, setSpeaking] = useState(false);

  // Stop any in-progress speech if this message unmounts (e.g. switching chats).
  useEffect(() => {
    return () => {
      if (speaking && speechSupported()) window.speechSynthesis.cancel();
    };
  }, [speaking]);

  if (!speechSupported() || text.trim() === "") return null;

  function toggle(): void {
    const synth = window.speechSynthesis;
    if (speaking) {
      synth.cancel();
      setSpeaking(false);
      return;
    }
    // Only one answer reads at a time; cancel() also fires onend for any other utterance so its
    // button resets.
    synth.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    setSpeaking(true);
    synth.speak(utterance);
  }

  return (
    <button
      data-testid="read-aloud"
      onClick={toggle}
      aria-label={speaking ? "Stop reading" : "Read answer aloud"}
      title={speaking ? "Stop reading" : "Read answer aloud"}
      style={{
        marginLeft: "0.4rem",
        fontSize: "0.8rem",
        lineHeight: 1,
        padding: "0.1rem 0.4rem",
        color: speaking ? "#b00" : "#555",
        verticalAlign: "middle",
      }}
    >
      <span aria-hidden="true">{speaking ? "■" : "▶"}</span>
    </button>
  );
}
