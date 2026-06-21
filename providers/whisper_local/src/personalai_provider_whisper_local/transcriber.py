"""In-process local Whisper transcriber via faster-whisper (CTranslate2), M9.2c (#300).

Implements the :class:`Transcriber` port with NO separate server: faster-whisper loads a Whisper
model in-process (downloaded once from Hugging Face, then cached and offline) and transcribes on
the CPU (Apple Silicon supported). Multilingual (~99 languages, auto-detected). The model is heavy
to load, so a single instance per (model, device, compute_type) is cached and reused; the blocking
inference runs in a worker thread so it doesn't stall the event loop.
"""

from __future__ import annotations

import asyncio
import io
from typing import Any

from personalai_contracts.ports import Transcription

# Cache of loaded models, keyed by (model, device, compute_type), so the weights load once.
_MODELS: dict[tuple[str, str, str], Any] = {}


def _load_model(model: str, device: str, compute_type: str) -> Any:
    key = (model, device, compute_type)
    cached = _MODELS.get(key)
    if cached is not None:
        return cached
    # Imported lazily so the heavy dependency is only pulled in when local STT is actually used.
    from faster_whisper import WhisperModel

    instance = WhisperModel(model, device=device, compute_type=compute_type)
    _MODELS[key] = instance
    return instance


class LocalWhisperTranscriber:
    """A :class:`Transcriber` running Whisper in-process via faster-whisper."""

    name = "whisper-local"

    def __init__(
        self,
        *,
        model: str = "large-v3-turbo",
        device: str = "auto",
        compute_type: str = "int8",
    ) -> None:
        self._model = model
        self._device = device
        self._compute_type = compute_type

    async def aclose(self) -> None:  # symmetry with the remote transcriber; nothing to close
        return None

    def _transcribe_sync(self, audio: bytes) -> Transcription:
        model = _load_model(self._model, self._device, self._compute_type)
        # faster-whisper decodes the container (webm/opus/wav/...) via av/ffmpeg from a file object.
        segments, info = model.transcribe(io.BytesIO(audio))
        text = "".join(segment.text for segment in segments).strip()
        return Transcription(text=text, language=getattr(info, "language", None))

    async def transcribe(
        self, audio: bytes, *, mime_type: str, filename: str = "audio.webm"
    ) -> Transcription:
        # Whisper inference is blocking + CPU-bound; run it off the event loop.
        return await asyncio.to_thread(self._transcribe_sync, audio)
