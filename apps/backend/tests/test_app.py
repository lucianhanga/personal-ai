"""HTTP behavior of the loopback API: health/version, auth, origin allowlist, structured output."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import pytest
from fastapi.testclient import TestClient

from personalai_backend import create_app
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
