"""OpenAI-compatible speech-to-text adapter (M9.2).

Implements the :class:`Transcriber` port against the OpenAI ``/v1/audio/transcriptions`` endpoint,
which is served by OpenAI **and** by local whisper servers (whisper.cpp-server, faster-whisper-
server, LocalAI). Remote calls run the injected egress guard first (ADR-0001); pointed at a local
server on loopback it works with egress disabled, keeping voice input local-first.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse

import httpx

from personalai_contracts.ports import Transcription

EgressGuard = Callable[[str], None]

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAICompatTranscriber:
    """A :class:`Transcriber` backed by an OpenAI-compatible ``/audio/transcriptions`` endpoint."""

    name = "openai-transcribe"

    def __init__(
        self,
        *,
        model: str,
        api_key: str = "",
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.AsyncClient | None = None,
        egress_guard: EgressGuard | None = None,
    ) -> None:
        self._model = model
        self._base = base_url.rstrip("/")
        self._host = urlparse(self._base).hostname or ""
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        self._owns_client = client is None
        self._egress_guard = egress_guard

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def transcribe(
        self, audio: bytes, *, mime_type: str, filename: str = "audio.webm"
    ) -> Transcription:
        if self._egress_guard is not None:
            self._egress_guard(self._host)
        # Bearer auth only when a key is set (local whisper servers usually need none).
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        response = await self._client.post(
            f"{self._base}/audio/transcriptions",
            headers=headers,
            files={"file": (filename, audio, mime_type)},
            data={"model": self._model},
        )
        response.raise_for_status()
        data = response.json()
        return Transcription(text=str(data.get("text", "")).strip(), language=data.get("language"))
