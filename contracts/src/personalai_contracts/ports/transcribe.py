"""Port: speech-to-text transcription (M9.2).

Turns recorded audio into text. Adapters speak a concrete API (e.g. the OpenAI-compatible
``/v1/audio/transcriptions`` endpoint, served by OpenAI or a local whisper server). Remote
adapters run the injected egress guard before any network call (ADR-0001); a local server on
loopback is always permitted by the guard, keeping voice input local-first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Transcription:
    """The result of transcribing audio: the recognized text (+ optional detected language)."""

    text: str
    language: str | None = None


@runtime_checkable
class Transcriber(Protocol):
    """Transcribes audio bytes to text."""

    name: str

    async def transcribe(
        self, audio: bytes, *, mime_type: str, filename: str = "audio.webm"
    ) -> Transcription:
        """Transcribe ``audio`` (raw bytes of ``mime_type``) into text."""
        ...
