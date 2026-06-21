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
import os
from typing import Any

from personalai_contracts.ports import Transcription

# Cache of loaded models, keyed by (model, device, compute_type, cpu_threads), so weights load once.
_MODELS: dict[tuple[str, str, str, int], Any] = {}


def _load_model(model: str, device: str, compute_type: str, cpu_threads: int) -> Any:
    key = (model, device, compute_type, cpu_threads)
    cached = _MODELS.get(key)
    if cached is not None:
        return cached
    # Imported lazily so the heavy dependency is only pulled in when local STT is actually used.
    from faster_whisper import WhisperModel

    instance = WhisperModel(
        model, device=device, compute_type=compute_type, cpu_threads=cpu_threads
    )
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
        cpu_threads: int = 0,
        language: str | None = None,
    ) -> None:
        self._model = model
        self._device = device
        self._compute_type = compute_type
        # faster-whisper's default only uses 4 CPU threads, which leaves a heavy model (e.g.
        # large-v3-turbo) far slower than it needs to be on a multi-core box. Default to all cores
        # (capped at 8 — beyond that CTranslate2's thread overhead stops paying off). 0/negative ->
        # auto. Callers may still pin a specific value.
        self._cpu_threads = cpu_threads if cpu_threads > 0 else min(os.cpu_count() or 4, 8)
        # None / "auto" / "" -> auto-detect; otherwise force this ISO-639-1 language. Pinning avoids
        # Whisper mis-detecting the spoken language (e.g. English heard as Bulgarian) on real audio.
        self._language = language if language and language.lower() != "auto" else None

    async def aclose(self) -> None:  # symmetry with the remote transcriber; nothing to close
        return None

    def _transcribe_sync(self, audio: bytes) -> Transcription:
        model = _load_model(self._model, self._device, self._compute_type, self._cpu_threads)
        # faster-whisper decodes the container (webm/opus/wav/...) via av/ffmpeg from a file object.
        # vad_filter strips silence/non-speech, which otherwise drags language detection toward a
        # wrong language and makes the model hallucinate phantom phrases on near-silent clips.
        segments, info = model.transcribe(
            io.BytesIO(audio), language=self._language, vad_filter=True
        )
        text = "".join(segment.text for segment in segments).strip()
        return Transcription(text=text, language=getattr(info, "language", None))

    async def transcribe(
        self, audio: bytes, *, mime_type: str, filename: str = "audio.webm"
    ) -> Transcription:
        # Whisper inference is blocking + CPU-bound; run it off the event loop.
        return await asyncio.to_thread(self._transcribe_sync, audio)
