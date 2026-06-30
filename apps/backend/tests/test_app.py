"""HTTP behavior of the loopback API: health/version, auth, origin allowlist, structured output."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from personalai_backend import create_app
from personalai_backend.app import (
    _RICH_OUTPUT,
    _sanitize_activities,
    _sanitize_attachments,
    _sanitize_display_content,
)
from personalai_backend.composition import bootstrap
from personalai_contracts.ports import (
    EmbeddingResult,
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    ModelCapabilities,
    ModelDescriptor,
    ModelProvider,
)
from personalai_contracts.testing import FakeModelProvider
from personalai_core import CoreConfig

TOKEN = "test-secret-token"


class RaisingProvider:
    """A provider whose calls fail — used to exercise error paths."""

    name = "boom"

    async def capabilities(self, model: str) -> ModelCapabilities:
        raise NotImplementedError

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        raise NotImplementedError

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        raise RuntimeError("ollama down")
        yield GenerationChunk()  # pragma: no cover - unreachable; makes this an async generator

    async def list_models(self) -> Sequence[ModelDescriptor]:
        raise RuntimeError("models unavailable")

    async def embed(self, texts: Sequence[str], model: str) -> EmbeddingResult:
        raise NotImplementedError


def _app_with_provider(provider_name: str, provider: ModelProvider) -> TestClient:
    config = CoreConfig(
        model_provider=provider_name,
        auth_token=TOKEN,
        allowed_origins=("http://localhost",),
    )
    boot = bootstrap(config=config)
    boot.registries.model_providers.register(provider_name, provider, overwrite=True)
    return TestClient(create_app(boot))


@pytest.fixture
def client() -> TestClient:
    config = CoreConfig(
        auth_token=TOKEN,
        allowed_origins=("http://localhost",),
        egress_enabled=False,
    )
    return TestClient(create_app(bootstrap(config=config)))


def test_oversized_request_body_is_rejected() -> None:
    config = CoreConfig(auth_token=TOKEN, max_request_bytes=100)
    client = TestClient(create_app(bootstrap(config=config)))
    # Body exceeds the configured ceiling -> 413 from the middleware (before routing/auth).
    resp = client.post("/api/v1/chat", content=b"x" * 500)
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "E_TOO_LARGE"


def test_normal_request_body_passes_the_limit(client: TestClient) -> None:
    # A small body is under the default ceiling and proceeds to normal handling (401 without auth).
    assert client.post("/api/v1/chat", json={"messages": []}).status_code == 401


def test_health_is_public(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_version(client: TestClient) -> None:
    resp = client.get("/version")
    assert resp.status_code == 200
    assert resp.json()["name"] == "personalai-backend"


def test_protected_route_requires_token(client: TestClient) -> None:
    assert client.get("/api/v1/status").status_code == 401
    assert (
        client.get("/api/v1/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
    )


def test_protected_route_with_valid_token_returns_structured_result(client: TestClient) -> None:
    resp = client.get("/api/v1/status", headers={"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["bind_host"] == "127.0.0.1"
    assert body["data"]["egress_enabled"] is False
    assert body["schema_version"] == "1.0.0"


def test_allowed_origin_gets_cors_header(client: TestClient) -> None:
    resp = client.get("/health", headers={"Origin": "http://localhost"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost"
    # Credentials allowed even in local mode: the SPA sends credentials:"include", which the browser
    # blocks without this header (#234).
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_disallowed_origin_gets_no_cors_header(client: TestClient) -> None:
    # CORS is an allowlist: a disallowed origin gets no ACAO header, so the browser blocks it.
    resp = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in resp.headers


def test_cors_preflight_allows_protected_route(client: TestClient) -> None:
    resp = client.options(
        "/api/v1/models",
        headers={
            "Origin": "http://localhost",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost"


def test_local_mode_no_token_uses_dev_login() -> None:
    # Local mode with no auth_token is zero-login (dev context), so protected routes work.
    client = TestClient(create_app(bootstrap(config=CoreConfig())))
    assert client.get("/api/v1/status").status_code == 200


def test_hosted_mode_no_credentials_is_denied() -> None:
    # Hosted mode requires a real session: no credentials => 401 (fail-closed), not dev-login.
    client = TestClient(create_app(bootstrap(config=CoreConfig(app_mode="hosted"))))
    assert client.get("/api/v1/status").status_code == 401


def test_non_loopback_bind_requires_auth_token() -> None:
    # Refuse to expose a non-loopback host without an auth token (fail-closed startup guard).
    config = CoreConfig(bind_host="0.0.0.0", auth_token=None)  # noqa: S104 - testing the guard
    with pytest.raises(RuntimeError, match="non-loopback host"):
        create_app(bootstrap(config=config))


def test_wildcard_origin_with_credentials_refuses_to_start() -> None:
    # '*' + allow_credentials=True would make Starlette reflect any origin -> credentialed CORS open
    # to the web. The startup guard must fail closed (#252).
    config = CoreConfig(auth_token=TOKEN, allowed_origins=("*",))
    with pytest.raises(RuntimeError, match="allowed_origins contains '\\*'"):
        create_app(bootstrap(config=config))


def test_wildcard_origin_in_a_mixed_allowlist_also_refuses() -> None:
    # A '*' hiding among explicit origins is just as dangerous and must also be rejected.
    config = CoreConfig(auth_token=TOKEN, allowed_origins=("https://app.example.com", " * "))
    with pytest.raises(RuntimeError, match="allowed_origins contains '\\*'"):
        create_app(bootstrap(config=config))


def test_explicit_allowlist_still_starts() -> None:
    # The normal case (a real, non-wildcard allowlist) boots fine — no behavior change.
    config = CoreConfig(auth_token=TOKEN, allowed_origins=("https://app.example.com",))
    app = create_app(bootstrap(config=config))
    assert app is not None


def test_models_endpoint_lists_capabilities() -> None:
    client = _app_with_provider("fake", FakeModelProvider(name="fake"))
    resp = client.get("/api/v1/models", headers={"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    names = [m["name"] for m in body["data"]["models"]]
    assert "fake" in names
    assert "capabilities" in body["data"]["models"][0]


def test_models_requires_token() -> None:
    client = _app_with_provider("fake", FakeModelProvider(name="fake"))
    assert client.get("/api/v1/models").status_code == 401


def test_providers_lists_registered() -> None:
    client = _app_with_provider("fake", FakeModelProvider(name="fake"))
    data = client.get("/api/v1/providers", headers={"Authorization": f"Bearer {TOKEN}"}).json()[
        "data"
    ]
    assert "ollama" in data["providers"]
    assert "fake" in data["providers"]
    assert data["default"] == "fake"


def test_models_unknown_provider_is_400() -> None:
    client = _app_with_provider("fake", FakeModelProvider(name="fake"))
    resp = client.get(
        "/api/v1/models", params={"provider": "ghost"}, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert resp.status_code == 400


def test_models_error_surfaces_structured_result() -> None:
    client = _app_with_provider("boom", RaisingProvider())
    resp = client.get(
        "/api/v1/models", params={"provider": "boom"}, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "E_MODELS"


def test_chat_unknown_provider_is_400() -> None:
    client = _app_with_provider("fake", FakeModelProvider(name="fake"))
    resp = client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"messages": [{"role": "user", "content": "hi"}], "provider": "ghost"},
    )
    assert resp.status_code == 400


def test_openai_registered_and_egress_blocked_by_default() -> None:
    # An API key registers the remote provider; with egress off, using it fails closed.
    config = CoreConfig(auth_token=TOKEN, openai_api_key="sk-test")
    client = TestClient(create_app(bootstrap(config=config)))
    providers = client.get(
        "/api/v1/providers", headers={"Authorization": f"Bearer {TOKEN}"}
    ).json()["data"]["providers"]
    assert "openai" in providers

    with client.stream(
        "POST",
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "provider": "openai",
            "model": "gpt-x",
        },
    ) as resp:
        body = "".join(resp.iter_text())
    assert "event: error" in body
    assert "egress is disabled" in body


def test_chat_requires_token() -> None:
    client = _app_with_provider("fake", FakeModelProvider(name="fake"))
    resp = client.post("/api/v1/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 401


class EmptyProvider:
    """A provider whose stream yields nothing (e.g. a reasoning model that produced no answer)."""

    name = "empty"

    async def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(
            text=True,
            vision=False,
            embeddings=False,
            tool_calling=False,
            structured_output=False,
            thinking=False,
            max_context_tokens=None,
        )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        raise NotImplementedError

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        return
        yield GenerationChunk()  # pragma: no cover - unreachable; makes this an async generator

    async def list_models(self) -> Sequence[ModelDescriptor]:
        return []

    async def embed(self, texts: Sequence[str], model: str) -> EmbeddingResult:
        raise NotImplementedError


class SlowProvider:
    """A provider whose stream hangs — used to exercise the per-turn timeout."""

    name = "slow"

    async def capabilities(self, model: str) -> ModelCapabilities:
        raise NotImplementedError

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        raise NotImplementedError

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        import asyncio

        await asyncio.sleep(30)  # pragma: no cover - cancelled by the turn timeout
        yield GenerationChunk()  # pragma: no cover

    async def list_models(self) -> Sequence[ModelDescriptor]:
        return []

    async def embed(self, texts: Sequence[str], model: str) -> EmbeddingResult:
        raise NotImplementedError


def test_chat_turn_timeout_emits_e_timeout() -> None:
    # A wedged model must not hang the turn: a 0s cap stops it and emits E_TIMEOUT (#256).
    config = CoreConfig(auth_token=TOKEN, agent_timeout_seconds=0)
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("slow", SlowProvider(), overwrite=True)
    client = TestClient(create_app(boot))
    with client.stream(
        "POST",
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"messages": [{"role": "user", "content": "hi"}], "provider": "slow"},
    ) as resp:
        body = "".join(resp.iter_text())
    assert "event: error" in body
    assert "E_TIMEOUT" in body


def test_chat_passes_attached_images_to_the_provider() -> None:
    # M9.1 vision: an image part on the user message reaches the provider's GenerationRequest.
    seen: list[tuple[str, ...]] = []

    class _Recorder(FakeModelProvider):
        async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
            for m in request.messages:
                if m.images:
                    seen.append(m.images)
            yield GenerationChunk(delta="ok")
            yield GenerationChunk(done=True, finish_reason="stop")

    client = _app_with_provider("rec", _Recorder(name="rec"))
    img = "data:image/png;base64,AAAA"
    with client.stream(
        "POST",
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={
            "messages": [{"role": "user", "content": "what is this?", "images": [img]}],
            "provider": "rec",
        },
    ) as resp:
        assert resp.status_code == 200
        "".join(resp.iter_text())
    assert seen and img in seen[0]


@respx.mock
def test_transcribe_endpoint_returns_text() -> None:
    # M9.2/#298: the endpoint builds the transcriber from the effective config (whisper base_url +
    # model) and returns the transcript. Mock the configured /audio/transcriptions endpoint.
    route = respx.post("http://whisper.test/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "hello from audio", "language": "en"})
    )
    config = CoreConfig(
        auth_token=TOKEN,
        transcribe_enabled=True,
        transcribe_provider="openai_compat",
        transcribe_base_url="http://whisper.test/v1",
        egress_allow_any=True,  # the test endpoint is non-loopback; allow it for the test
        egress_enabled=True,
    )
    client = TestClient(create_app(bootstrap(config=config)))
    resp = client.post(
        "/api/v1/audio/transcribe",
        headers={"Authorization": f"Bearer {TOKEN}"},
        files={"file": ("rec.webm", b"\x00\x01", "audio/webm")},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["text"] == "hello from audio"
    assert route.called


def test_transcribe_endpoint_503_when_disabled() -> None:
    # transcribe_enabled=False -> 503, and /status reports it disabled.
    client = TestClient(
        create_app(bootstrap(config=CoreConfig(auth_token=TOKEN, transcribe_enabled=False)))
    )
    resp = client.post(
        "/api/v1/audio/transcribe",
        headers={"Authorization": f"Bearer {TOKEN}"},
        files={"file": ("rec.webm", b"\x00", "audio/webm")},
    )
    assert resp.status_code == 503
    status_data = client.get("/api/v1/status", headers={"Authorization": f"Bearer {TOKEN}"}).json()[
        "data"
    ]
    assert status_data["transcribe_enabled"] is False


def test_transcribe_local_provider_uses_in_process_whisper() -> None:
    # #300: with transcribe_provider="local" (the default) the endpoint uses the in-process
    # faster-whisper adapter — patched here so no model is downloaded/loaded in tests.
    from personalai_provider_whisper_local import transcriber as whisper_mod

    class _FakeModel:
        def __init__(self, *a: object, **k: object) -> None: ...
        def transcribe(self, audio: object, **k: object) -> tuple[list[object], object]:
            seg = type("S", (), {"text": "hallo welt"})()
            info = type("I", (), {"language": "de"})()
            return [seg], info

    import sys
    import types as _types

    whisper_mod._MODELS.clear()
    fake = _types.ModuleType("faster_whisper")
    fake.WhisperModel = _FakeModel  # type: ignore[attr-defined]
    sys.modules["faster_whisper"] = fake

    client = TestClient(
        create_app(bootstrap(config=CoreConfig(auth_token=TOKEN, transcribe_provider="local")))
    )
    resp = client.post(
        "/api/v1/audio/transcribe",
        headers={"Authorization": f"Bearer {TOKEN}"},
        files={"file": ("rec.webm", b"\x00\x01", "audio/webm")},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["text"] == "hallo welt"


def test_status_reports_transcribe_enabled_by_default() -> None:
    # #298: STT is enabled by default, so /status reports it on (the UI shows the mic).
    client = TestClient(create_app(bootstrap(config=CoreConfig(auth_token=TOKEN))))
    data = client.get("/api/v1/status", headers={"Authorization": f"Bearer {TOKEN}"}).json()["data"]
    assert data["transcribe_enabled"] is True


def test_status_reports_tts_enabled() -> None:
    # M9.3: read-aloud availability is on by default and off when disabled, so the UI can hide it.
    client = TestClient(create_app(bootstrap(config=CoreConfig(auth_token=TOKEN))))
    on = client.get("/api/v1/status", headers={"Authorization": f"Bearer {TOKEN}"}).json()["data"]
    assert on["tts_enabled"] is True

    off_client = TestClient(
        create_app(bootstrap(config=CoreConfig(auth_token=TOKEN, tts_enabled=False)))
    )
    off = off_client.get("/api/v1/status", headers={"Authorization": f"Bearer {TOKEN}"}).json()[
        "data"
    ]
    assert off["tts_enabled"] is False


def test_chat_empty_completion_emits_notice() -> None:
    # An empty turn (no answer/tools) must surface a notice, not close the stream silently (#224).
    client = _app_with_provider("empty", EmptyProvider())
    with client.stream(
        "POST",
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"messages": [{"role": "user", "content": "hi"}], "provider": "empty"},
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    assert "event: error" in body
    assert "E_EMPTY" in body


def test_chat_with_graph_enabled_streams_plan_answer_critique() -> None:
    # M8.1b/#290: with agent_mode="multi" the tool path runs the planner -> researcher -> critic
    # graph, so the stream carries plan + critique steps around the answer (plus the done frame).
    config = CoreConfig(auth_token=TOKEN, agent_mode="multi")
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("fake", FakeModelProvider(name="fake"), overwrite=True)
    client = TestClient(create_app(boot))
    with client.stream(
        "POST",
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={
            "messages": [{"role": "user", "content": "hi there"}],
            "provider": "fake",
            "use_tools": True,
        },
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    assert "echo:" in body and '"done": true' in body
    assert "event: plan" in body and "event: critique" in body
    # Standard accuracy mode: no verifier (LLM-judge) step.
    assert "event: verification" not in body


def test_accurate_mode_streams_a_verification_step() -> None:
    # M8.2/#261: agent_accuracy_mode="accurate" adds the LLM-judge verifier after the critic, which
    # emits a verification step. The fake judge returns a structured "pass" verdict (echo of the
    # JSON we feed it), so the ladder verifies and finalizes.
    judge = FakeModelProvider(name="fake")

    async def _gen(request: GenerationRequest) -> GenerationResult:
        last = request.messages[-1].content if request.messages else ""
        if "Draft answer to verify" in last:
            return GenerationResult(text='{"verdict": "pass", "reason": "ok"}', model=request.model)
        return GenerationResult(text="echo", model=request.model)

    judge.generate = _gen  # type: ignore[method-assign]
    config = CoreConfig(auth_token=TOKEN, agent_mode="multi", agent_accuracy_mode="accurate")
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("fake", judge, overwrite=True)
    client = TestClient(create_app(boot))
    with client.stream(
        "POST",
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "provider": "fake",
            "use_tools": True,
        },
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    assert "event: verification" in body
    assert '"verdict": "pass"' in body


def test_chat_streams_deltas() -> None:
    client = _app_with_provider("fake", FakeModelProvider(name="fake"))
    with client.stream(
        "POST",
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"messages": [{"role": "user", "content": "hi there"}]},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = "".join(resp.iter_text())
    # FakeModelProvider streams "echo: hi there" across SSE data frames.
    assert "echo:" in body
    assert "hi" in body and "there" in body
    assert '"done": true' in body


def test_chat_invalid_body_is_rejected() -> None:
    client = _app_with_provider("fake", FakeModelProvider(name="fake"))
    resp = client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"messages": [{"role": "bogus", "content": "hi"}]},
    )
    assert resp.status_code == 422  # schema validation (fail-closed)


def test_chat_errors_surface_as_sse_error_event() -> None:
    client = _app_with_provider("boom", RaisingProvider())
    with client.stream(
        "POST",
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"messages": [{"role": "user", "content": "hi"}]},
    ) as resp:
        body = "".join(resp.iter_text())
    assert "event: error" in body
    assert "E_GENERATION" in body
    assert "ollama down" in body


def test_lifespan_closes_providers() -> None:
    # Using the client as a context manager runs lifespan startup/shutdown; shutdown closes the
    # bootstrap-registered Ollama provider's HTTP client.
    config = CoreConfig(auth_token=TOKEN)
    boot = bootstrap(config=config)
    # "ollama" (has aclose) + a fake (no aclose) exercises both shutdown branches.
    boot.registries.model_providers.register("fake", FakeModelProvider(name="fake"))
    with TestClient(create_app(boot)) as ctx_client:
        assert ctx_client.get("/health").status_code == 200


def test_entrypoint_module_importable() -> None:
    # `python -m personalai_backend` entrypoint exists and is callable (not invoked here).
    import personalai_backend.__main__ as entry

    assert callable(entry.main)


def test_agent_context_is_none_without_security() -> None:
    # _agent_context fails soft to None when no SecurityContext is in scope (graph gets no tenant).
    from personalai_backend.app import _agent_context

    assert _agent_context("c1") is None


def test_resume_without_db_is_503() -> None:
    # Durable resume (M8.1c) needs a DB-backed tenant checkpoint; without storage it fails closed.
    client = TestClient(
        create_app(bootstrap(config=CoreConfig(database_url="postgresql://nope@127.0.0.1:1/none")))
    )
    resp = client.post("/api/v1/chat/some-run/resume", json={"decision": "approve"})
    assert resp.status_code == 503


def test_context_breakdown_summarizes_non_empty_components() -> None:
    # The context view (#290) lists each non-empty component with its size; empties are skipped.
    from personalai_backend.app import _context_breakdown
    from personalai_contracts.ports import ChatMessage, Role

    bd = _context_breakdown(
        [
            ("Grounding", [ChatMessage(Role.SYSTEM, "x" * 100)]),
            ("Empty", []),
            ("Documents", [ChatMessage(Role.SYSTEM, "y" * 50), ChatMessage(Role.SYSTEM, "z" * 50)]),
        ]
    )
    labels = {i["label"]: i for i in bd["items"]}
    assert "Empty" not in labels
    assert labels["Grounding"]["chars"] == 100
    assert labels["Documents"]["count"] == 2 and labels["Documents"]["chars"] == 100
    assert bd["total_chars"] == 200


def test_followup_adds_an_interpreted_request_to_the_context() -> None:
    # Option A: a follow-up (prior turn exists) is contextualized into a standalone "Interpreted
    # request" that anchors retrieval/tools and shows up in the context breakdown.
    client = _app_with_provider("fake", FakeModelProvider(name="fake"))
    body = {
        "messages": [
            {"role": "user", "content": "weather in munich?"},
            {"role": "assistant", "content": "It's sunny."},
            {"role": "user", "content": "and tomorrow?"},
        ],
        "provider": "fake",
    }
    with client.stream(
        "POST", "/api/v1/chat", headers={"Authorization": f"Bearer {TOKEN}"}, json=body
    ) as resp:
        assert resp.status_code == 200
        text = "".join(resp.iter_text())
    assert "Interpreted request" in text  # the standalone query was added


def test_single_question_skips_the_interpreted_request() -> None:
    # A first/only question is already standalone -> no extra rewrite call, no interpreted-request.
    client = _app_with_provider("fake", FakeModelProvider(name="fake"))
    body = {"messages": [{"role": "user", "content": "weather in munich?"}], "provider": "fake"}
    with client.stream(
        "POST", "/api/v1/chat", headers={"Authorization": f"Bearer {TOKEN}"}, json=body
    ) as resp:
        assert resp.status_code == 200
        text = "".join(resp.iter_text())
    assert "Interpreted request" not in text


# --- image description endpoint (#419) ----------------------------------------------------------

_VISION = ModelCapabilities(text=True, vision=True)
_PNG = ("cat.png", b"\x89PNG\r\n\x1a\n", "image/png")


def test_describe_image_returns_a_description() -> None:
    client = _app_with_provider("fake", FakeModelProvider(name="fake", capabilities=_VISION))
    res = client.post(
        "/api/v1/images/describe",
        headers={"Authorization": f"Bearer {TOKEN}"},
        files={"file": _PNG},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["data"]["description"].startswith("echo:")  # FakeModelProvider echoes the prompt


def test_describe_image_no_vision_model_is_structured_error() -> None:
    # The default FakeModelProvider has vision=False -> a structured E_NO_VISION_MODEL, not a 500.
    client = _app_with_provider("fake", FakeModelProvider(name="fake"))
    res = client.post(
        "/api/v1/images/describe",
        headers={"Authorization": f"Bearer {TOKEN}"},
        files={"file": _PNG},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "E_NO_VISION_MODEL"


def test_describe_image_oversized_is_413() -> None:
    config = CoreConfig(model_provider="fake", auth_token=TOKEN, max_upload_bytes=4)
    boot = bootstrap(config=config)
    boot.registries.model_providers.register(
        "fake", FakeModelProvider(name="fake", capabilities=_VISION), overwrite=True
    )
    client = TestClient(create_app(boot))
    res = client.post(
        "/api/v1/images/describe",
        headers={"Authorization": f"Bearer {TOKEN}"},
        files={"file": ("big.png", b"xxxxxxxxxx", "image/png")},
    )
    assert res.status_code == 413


def test_describe_image_requires_token() -> None:
    client = _app_with_provider("fake", FakeModelProvider(name="fake", capabilities=_VISION))
    res = client.post("/api/v1/images/describe", files={"file": _PNG})
    assert res.status_code == 401


# --- document text-extraction endpoint (#416, tier-1 of #420) ------------------------------------


def test_extract_file_returns_plain_text(client: TestClient) -> None:
    res = client.post(
        "/api/v1/files/extract",
        headers={"Authorization": f"Bearer {TOKEN}"},
        files={"file": ("notes.txt", b"hello document world", "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["data"]["name"] == "notes.txt"
    assert body["data"]["text"] == "hello document world"
    assert body["data"]["truncated"] is False


def test_extract_file_reads_markdown(client: TestClient) -> None:
    res = client.post(
        "/api/v1/files/extract",
        headers={"Authorization": f"Bearer {TOKEN}"},
        files={"file": ("readme.md", b"# Title\n\nsome **markdown** body", "text/markdown")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "markdown" in body["data"]["text"]


def test_extract_file_unsupported_type_is_structured_error(client: TestClient) -> None:
    # An unparseable type yields a structured E_UNSUPPORTED_FILE, not a 500.
    res = client.post(
        "/api/v1/files/extract",
        headers={"Authorization": f"Bearer {TOKEN}"},
        files={"file": ("movie.mp4", b"\x00\x00\x00\x18ftyp", "video/mp4")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "E_UNSUPPORTED_FILE"


def test_extract_file_oversized_is_413() -> None:
    config = CoreConfig(model_provider="fake", auth_token=TOKEN, max_upload_bytes=4)
    client = TestClient(create_app(bootstrap(config=config)))
    res = client.post(
        "/api/v1/files/extract",
        headers={"Authorization": f"Bearer {TOKEN}"},
        files={"file": ("big.txt", b"way too many bytes", "text/plain")},
    )
    assert res.status_code == 413


def test_extract_file_requires_token(client: TestClient) -> None:
    res = client.post("/api/v1/files/extract", files={"file": ("notes.txt", b"hi", "text/plain")})
    assert res.status_code == 401


# --- eager endpoints surface model/ms/usage for resource activities (#424) -----------------------


def test_describe_image_returns_model_ms_usage() -> None:
    # #424: the describe endpoint surfaces the model the provider used, an eager-call wall-clock,
    # and token usage so the UI can assemble a resource activity. Additive to the description.
    client = _app_with_provider("fake", FakeModelProvider(name="fake", capabilities=_VISION))
    res = client.post(
        "/api/v1/images/describe",
        headers={"Authorization": f"Bearer {TOKEN}"},
        files={"file": _PNG},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["description"].startswith("echo:")  # existing caller contract is preserved
    assert isinstance(data["model"], str) and data["model"]  # the model actually used
    assert isinstance(data["ms"], int) and data["ms"] >= 0  # wall-clock in ms
    assert "usage" in data  # present (None when the provider reported no tokens)


def test_extract_file_returns_null_model_and_ms(client: TestClient) -> None:
    # #424: document extraction is a local CPU parse — no model. ``model``/``usage`` are honestly
    # null; ``ms`` is the parse wall-clock so the activity still shows a duration.
    res = client.post(
        "/api/v1/files/extract",
        headers={"Authorization": f"Bearer {TOKEN}"},
        files={"file": ("notes.txt", b"hello document world", "text/plain")},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["text"] == "hello document world"  # existing caller contract is preserved
    assert data["model"] is None
    assert data["usage"] is None
    assert isinstance(data["ms"], int) and data["ms"] >= 0


@respx.mock
def test_transcribe_returns_model_ms_usage() -> None:
    # #424: audio transcription surfaces the configured Whisper model id + wall-clock; STT reports
    # no tokens so usage is None.
    route = respx.post("http://whisper.test/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "hi", "language": "en"})
    )
    config = CoreConfig(
        auth_token=TOKEN,
        transcribe_enabled=True,
        transcribe_provider="openai_compat",
        transcribe_base_url="http://whisper.test/v1",
        transcribe_model="whisper-1",
        egress_allow_any=True,
        egress_enabled=True,
    )
    client = TestClient(create_app(bootstrap(config=config)))
    res = client.post(
        "/api/v1/audio/transcribe",
        headers={"Authorization": f"Bearer {TOKEN}"},
        files={"file": ("rec.webm", b"\x00\x01", "audio/webm")},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["text"] == "hi"  # existing caller contract is preserved
    assert data["model"] == "whisper-1"
    assert data["usage"] is None
    assert isinstance(data["ms"], int) and data["ms"] >= 0
    assert route.called


# --- _sanitize_activities: the security-critical persist boundary (#424) --------------------------


def _activity(**over: object) -> dict[str, object]:
    base = {
        "kind": "resource",
        "action": "image_described",
        "text": "Described image — cat.jpg",
        "ref": "cat.jpg",
        "ts": 1_700_000_000,
        "model": "qwen2.5-vl:7b",
        "ms": 2300,
    }
    base.update(over)
    return base


def test_sanitize_activities_keeps_a_valid_item() -> None:
    out = _sanitize_activities([_activity()])
    assert len(out) == 1
    item = out[0]
    assert item["kind"] == "resource"
    assert item["action"] == "image_described"
    assert item["text"] == "Described image — cat.jpg"
    assert item["ref"] == "cat.jpg"
    assert item["model"] == "qwen2.5-vl:7b"
    assert item["ms"] == 2300
    assert item["ts"] == 1_700_000_000


def test_sanitize_activities_non_list_is_empty() -> None:
    assert _sanitize_activities(None) == []
    assert _sanitize_activities("not a list") == []
    assert _sanitize_activities({"action": "image_described"}) == []


def test_sanitize_activities_forces_kind_resource() -> None:
    out = _sanitize_activities([_activity(kind="evil")])
    assert out[0]["kind"] == "resource"  # client value ignored


def test_sanitize_activities_drops_unknown_action() -> None:
    assert _sanitize_activities([_activity(action="shell_exec")]) == []
    assert _sanitize_activities([_activity(action=None)]) == []


def test_sanitize_activities_requires_text_and_ref() -> None:
    assert _sanitize_activities([_activity(text="")]) == []
    assert _sanitize_activities([_activity(text="   ")]) == []
    assert _sanitize_activities([_activity(ref="")]) == []


def test_sanitize_activities_drops_unknown_keys() -> None:
    out = _sanitize_activities([_activity(injected="<script>", secret="leak")])
    assert "injected" not in out[0]
    assert "secret" not in out[0]


def test_sanitize_activities_caps_string_lengths() -> None:
    out = _sanitize_activities([_activity(text="x" * 5000, ref="r" * 5000, model="m" * 5000)])
    item = out[0]
    assert len(item["text"]) == 200
    assert len(item["ref"]) == 256
    assert len(item["model"]) == 128


def test_sanitize_activities_clamps_ms() -> None:
    assert _sanitize_activities([_activity(ms=-5)])[0]["ms"] == 0
    assert _sanitize_activities([_activity(ms=10**12)])[0]["ms"] == 86_400_000
    assert _sanitize_activities([_activity(ms="not-a-number")])[0]["ms"] == 0


def test_sanitize_activities_clamps_far_future_ts_to_now() -> None:
    import time as _time

    now = int(_time.time())
    out = _sanitize_activities([_activity(ts=now + 10_000)])
    assert out[0]["ts"] <= now + 60  # far-future clamped
    assert _sanitize_activities([_activity(ts="garbage")])[0]["ts"] >= now - 5  # garbage -> now
    assert _sanitize_activities([_activity(ts=-100)])[0]["ts"] == 0  # negative clamped to 0


def test_sanitize_activities_bounds_count_to_24() -> None:
    out = _sanitize_activities([_activity(ref=f"f{i}.jpg") for i in range(100)])
    assert len(out) == 24  # overflow dropped silently, never raises


def test_sanitize_activities_keeps_only_int_usage_fields() -> None:
    out = _sanitize_activities(
        [_activity(usage={"prompt_tokens": 12, "completion_tokens": 8, "evil": "x"})]
    )
    assert out[0]["usage"] == {"prompt_tokens": 12, "completion_tokens": 8}
    # clamps oversized token counts
    big = _sanitize_activities([_activity(usage={"prompt_tokens": 10**9})])
    assert big[0]["usage"]["prompt_tokens"] == 10_000_000
    # non-dict usage is dropped entirely
    assert "usage" not in _sanitize_activities([_activity(usage="lots")])[0]


def test_sanitize_activities_preserves_error_status() -> None:
    out = _sanitize_activities([_activity(status="error", error="vision model unavailable")])
    assert out[0]["status"] == "error"
    assert out[0]["error"] == "vision model unavailable"
    # a non-error status is not propagated (defaults to ok implicitly)
    assert "status" not in _sanitize_activities([_activity(status="ok")])[0]


def test_sanitize_activities_mixed_valid_and_invalid() -> None:
    out = _sanitize_activities(
        [
            _activity(ref="good.jpg"),
            "not a dict",
            _activity(action="bogus"),
            _activity(action="document_extracted", text="Extracted — spec.pdf", ref="spec.pdf"),
        ]
    )
    refs = [i["ref"] for i in out]
    assert refs == ["good.jpg", "spec.pdf"]


# --- #426: sent-message attachment display data — the persist boundary ---------------------------


def test_sanitize_display_content_keeps_a_typed_prompt() -> None:
    assert _sanitize_display_content("Summarize the contract") == "Summarize the contract"


def test_sanitize_display_content_none_and_blank_become_none() -> None:
    # Old turns send no display_content; attachments-only turns send an empty/whitespace prompt.
    assert _sanitize_display_content(None) is None
    assert _sanitize_display_content("") is None
    assert _sanitize_display_content("   \n  ") is None


def test_sanitize_display_content_caps_length() -> None:
    out = _sanitize_display_content("x" * 500_000)
    assert out is not None
    assert len(out) == 100_000  # _DISPLAY_CONTENT_CAP


def test_sanitize_attachments_documents_keeps_name_and_text() -> None:
    out = _sanitize_attachments([{"name": "a.pdf", "text": "full text"}], "text")
    assert out == [{"name": "a.pdf", "text": "full text"}]


def test_sanitize_attachments_audio_keeps_name_and_transcript() -> None:
    out = _sanitize_attachments([{"name": "c.m4a", "transcript": "spoken words"}], "transcript")
    assert out == [{"name": "c.m4a", "transcript": "spoken words"}]


def test_sanitize_attachments_non_list_is_empty() -> None:
    assert _sanitize_attachments(None, "text") == []
    assert _sanitize_attachments("not a list", "text") == []
    assert _sanitize_attachments({"name": "a"}, "text") == []


def test_sanitize_attachments_drops_unknown_keys() -> None:
    # The security-relevant bit: only name + the text field survive; injected keys are dropped.
    out = _sanitize_attachments(
        [{"name": "a.pdf", "text": "t", "evil": "<script>", "id": "x"}], "text"
    )
    assert out == [{"name": "a.pdf", "text": "t"}]


def test_sanitize_attachments_requires_a_name() -> None:
    assert _sanitize_attachments([{"name": "", "text": "t"}], "text") == []
    assert _sanitize_attachments([{"name": "   ", "text": "t"}], "text") == []
    assert _sanitize_attachments([{"text": "t"}], "text") == []


def test_sanitize_attachments_allows_empty_text() -> None:
    # A document/audio with no extracted text is still a valid chip (name + empty body).
    assert _sanitize_attachments([{"name": "a.pdf"}], "text") == [{"name": "a.pdf", "text": ""}]


def test_sanitize_attachments_caps_name_and_text_lengths() -> None:
    out = _sanitize_attachments([{"name": "n" * 5000, "text": "t" * 500_000}], "text")
    assert len(out[0]["name"]) == 256  # _ATTACHMENT_NAME_CAP
    assert len(out[0]["text"]) == 200_000  # _ATTACHMENT_TEXT_CAP


def test_sanitize_attachments_bounds_count() -> None:
    out = _sanitize_attachments([{"name": f"d{i}.pdf", "text": "t"} for i in range(100)], "text")
    assert len(out) == 32  # _MAX_ATTACHMENTS_PER_TURN; overflow dropped silently, never raises


def test_sanitize_attachments_mixed_valid_and_invalid() -> None:
    out = _sanitize_attachments(
        [
            {"name": "good.pdf", "text": "a"},
            "not a dict",
            {"name": "", "text": "dropped"},
            {"name": "also-good.pdf", "text": "b"},
        ],
        "text",
    )
    assert [i["name"] for i in out] == ["good.pdf", "also-good.pdf"]


# --- Rich-output injection tests (#517) ---

def test_rich_output_system_message_injected_when_enabled() -> None:
    """_RICH_OUTPUT system message is present in the generation request when enabled."""
    captured: list[GenerationRequest] = []

    class _Recorder(FakeModelProvider):
        async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
            captured.append(request)
            yield GenerationChunk(delta="ok")
            yield GenerationChunk(done=True, finish_reason="stop")

    config = CoreConfig(
        auth_token=TOKEN,
        model_provider="rec",
        rich_output_enabled=True,
        grounding_enabled=False,  # isolate; don't mix with the grounding system msg
    )
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("rec", _Recorder(name="rec"), overwrite=True)
    client = TestClient(create_app(boot))

    with client.stream(
        "POST",
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"messages": [{"role": "user", "content": "draw me a diagram"}], "provider": "rec"},
    ) as resp:
        assert resp.status_code == 200
        "".join(resp.iter_text())

    assert captured, "provider never called"
    system_contents = [m.content for m in captured[0].messages if m.role == "system"]
    assert any(_RICH_OUTPUT in c for c in system_contents), (
        f"_RICH_OUTPUT not found in system messages: {system_contents}"
    )


def test_rich_output_system_message_absent_when_disabled() -> None:
    """_RICH_OUTPUT system message is NOT present when rich_output_enabled=False."""
    captured: list[GenerationRequest] = []

    class _Recorder(FakeModelProvider):
        async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
            captured.append(request)
            yield GenerationChunk(delta="ok")
            yield GenerationChunk(done=True, finish_reason="stop")

    config = CoreConfig(
        auth_token=TOKEN,
        model_provider="rec",
        rich_output_enabled=False,  # explicit off (default is now on, #517)
    )
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("rec", _Recorder(name="rec"), overwrite=True)
    client = TestClient(create_app(boot))

    with client.stream(
        "POST",
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"messages": [{"role": "user", "content": "hello"}], "provider": "rec"},
    ) as resp:
        assert resp.status_code == 200
        "".join(resp.iter_text())

    assert captured, "provider never called"
    system_contents = [m.content for m in captured[0].messages if m.role == "system"]
    assert not any(_RICH_OUTPUT in c for c in system_contents), (
        f"_RICH_OUTPUT unexpectedly present in system messages: {system_contents}"
    )


# --- Image-localise endpoint tests (#517) ------------------------------------


def _coro(value: object) -> object:
    """Return a coroutine that immediately resolves to *value*.

    Used to replace async functions with monkeypatch when the replacement must
    return an awaitable (FastAPI awaits the endpoint dependency internally).
    """

    async def _inner() -> object:
        return value

    return _inner()


def _localize_client(
    *, egress_enabled: bool = True, allowed_hosts: tuple[str, ...] = ()
) -> TestClient:
    """Build a TestClient configured for the localize endpoint tests."""
    config = CoreConfig(
        auth_token=TOKEN,
        egress_enabled=egress_enabled,
        allowed_egress_hosts=allowed_hosts,
        egress_allow_any=not allowed_hosts and egress_enabled,
    )
    return TestClient(create_app(bootstrap(config=config)))


_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def test_localize_image_needs_approval_when_host_not_allowlisted() -> None:
    # Egress enabled but the host is not on the allowlist -> needs_approval signal.
    client = _localize_client(egress_enabled=True, allowed_hosts=("other.example.com",))
    resp = client.post(
        "/api/v1/images/localize",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"url": "https://cdn.example.com/img.png"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    # The response carries both an error code and a data payload so the UI can
    # distinguish the "needs approval" gate from a hard failure.
    assert body["error"]["code"] == "E_EGRESS_APPROVAL_NEEDED"
    assert body["data"]["needs_approval"] is True
    assert body["data"]["host"] == "cdn.example.com"


def test_localize_image_success_returns_data_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # With egress allowed (allow_any=True) and a monkeypatched fetch, the endpoint
    # returns a data: URL.
    monkeypatch.setattr(
        "personalai_backend.app._ssrf.fetch_image",
        lambda url, **kw: _coro(("image/png", _PNG_BYTES)),
    )
    client = _localize_client(egress_enabled=True)
    resp = client.post(
        "/api/v1/images/localize",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"url": "https://cdn.example.com/img.png"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data_url: str = body["data"]["data_url"]
    assert data_url.startswith("data:image/png;base64,")


def test_localize_image_blocked_returns_e_image_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    # fetch_image raises SsrfBlockedError -> endpoint returns E_IMAGE_BLOCKED (not a 5xx).
    from personalai_core.security.ssrf import SsrfBlockedError as _SsrfErr

    async def _raise(url: str, **kw: object) -> tuple[str, bytes]:
        raise _SsrfErr("image could not be fetched")

    monkeypatch.setattr("personalai_backend.app._ssrf.fetch_image", _raise)
    client = _localize_client(egress_enabled=True)
    resp = client.post(
        "/api/v1/images/localize",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"url": "https://cdn.example.com/img.png"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "E_IMAGE_BLOCKED"


def test_localize_image_requires_token() -> None:
    client = _localize_client(egress_enabled=True)
    resp = client.post(
        "/api/v1/images/localize",
        json={"url": "https://cdn.example.com/img.png"},
    )
    assert resp.status_code == 401


def test_localize_image_egress_disabled_returns_needs_approval() -> None:
    # Egress entirely disabled -> same needs_approval gate (the user must allow the host first).
    client = _localize_client(egress_enabled=False)
    resp = client.post(
        "/api/v1/images/localize",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"url": "https://cdn.example.com/img.png"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "E_EGRESS_APPROVAL_NEEDED"
    assert body["data"]["needs_approval"] is True


