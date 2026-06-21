"""LocalWhisperTranscriber with faster-whisper mocked (no model download / inference in tests)."""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

from personalai_provider_whisper_local import LocalWhisperTranscriber
from personalai_provider_whisper_local import transcriber as mod

from personalai_contracts.ports import Transcriber


def test_is_a_transcriber() -> None:
    assert isinstance(LocalWhisperTranscriber(model="small"), Transcriber)


class _Segment:
    def __init__(self, text: str) -> None:
        self.text = text


class _Info:
    language = "ro"


class _FakeModel:
    instances: list[tuple[str, str, str, int]] = []

    def __init__(self, model: str, *, device: str, compute_type: str, cpu_threads: int) -> None:
        _FakeModel.instances.append((model, device, compute_type, cpu_threads))

    def transcribe(self, audio: Any) -> tuple[list[_Segment], _Info]:
        return [_Segment(" Salut, "), _Segment("ce faci?")], _Info()


def _install_fake_faster_whisper() -> None:
    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = _FakeModel  # type: ignore[attr-defined]
    sys.modules["faster_whisper"] = fake


def test_transcribes_via_faster_whisper_and_joins_segments() -> None:
    _install_fake_faster_whisper()
    mod._MODELS.clear()
    _FakeModel.instances.clear()
    t = LocalWhisperTranscriber(model="large-v3-turbo")

    result = asyncio.run(t.transcribe(b"\x00\x01webm", mime_type="audio/webm"))
    assert result.text == "Salut, ce faci?"  # segments joined + trimmed
    assert result.language == "ro"  # multilingual auto-detection surfaced
    # One model built with the expected model/device/compute, and a positive CPU-thread count
    # (defaults to the core count, capped) rather than faster-whisper's slow 4-thread default.
    assert len(_FakeModel.instances) == 1
    model_name, device, compute, cpu_threads = _FakeModel.instances[0]
    assert (model_name, device, compute) == ("large-v3-turbo", "auto", "int8")
    assert cpu_threads >= 1


def test_model_is_loaded_once_and_cached() -> None:
    _install_fake_faster_whisper()
    mod._MODELS.clear()
    _FakeModel.instances.clear()
    t = LocalWhisperTranscriber(model="small")
    asyncio.run(t.transcribe(b"a", mime_type="audio/webm"))
    asyncio.run(t.transcribe(b"b", mime_type="audio/webm"))
    assert len(_FakeModel.instances) == 1  # weights loaded once, reused
