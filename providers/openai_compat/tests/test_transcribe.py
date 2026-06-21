"""OpenAICompatTranscriber against a mocked /audio/transcriptions endpoint (respx)."""

from __future__ import annotations

import asyncio

import httpx
import respx

from personalai_contracts.ports import Transcriber
from personalai_provider_openai import OpenAICompatTranscriber

BASE = "https://api.example.test/v1"


def _run(transcriber: OpenAICompatTranscriber) -> object:
    async def _inner() -> object:
        try:
            return await transcriber.transcribe(b"\x00\x01audio", mime_type="audio/webm")
        finally:
            await transcriber.aclose()

    return asyncio.run(_inner())


def test_is_a_transcriber() -> None:
    assert isinstance(OpenAICompatTranscriber(model="whisper-1", base_url=BASE), Transcriber)


@respx.mock
def test_transcribe_posts_multipart_and_returns_text() -> None:
    route = respx.post(f"{BASE}/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "  hello world  ", "language": "en"})
    )
    result = _run(OpenAICompatTranscriber(model="whisper-1", api_key="sk-test", base_url=BASE))
    assert result.text == "hello world"  # trimmed
    assert result.language == "en"
    req = route.calls[0].request
    assert req.headers["authorization"] == "Bearer sk-test"
    assert b"whisper-1" in req.content  # the model field in the multipart body
    assert b"audio/webm" in req.content


@respx.mock
def test_transcribe_omits_auth_header_when_no_key() -> None:
    # Local whisper servers usually need no key — don't send an empty bearer.
    route = respx.post(f"{BASE}/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "hi"})
    )
    _run(OpenAICompatTranscriber(model="whisper-1", base_url=BASE))
    assert "authorization" not in route.calls[0].request.headers


def test_transcribe_runs_the_egress_guard() -> None:
    calls: list[str] = []
    t = OpenAICompatTranscriber(
        model="whisper-1", base_url="https://blocked.test/v1", egress_guard=calls.append
    )

    @respx.mock
    def _go() -> None:
        respx.post("https://blocked.test/v1/audio/transcriptions").mock(
            return_value=httpx.Response(200, json={"text": "x"})
        )
        _run(t)

    _go()
    assert calls == ["blocked.test"]  # the guard was called with the host before the request
