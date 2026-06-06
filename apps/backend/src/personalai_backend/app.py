"""The PersonalAI FastAPI application (loopback by default).

Security posture (ADR / THREAT-MODEL):
- Binds to ``127.0.0.1`` by default; LAN/remote is opt-in via ``CoreConfig.bind_host``.
- Browser requests are restricted to an **origin allowlist** (defense against cross-site calls);
  non-browser clients (curl, the test client) send no ``Origin`` and are allowed.
- Protected routes require a **bearer token** compared in constant time.
- Responses use the structured-output schemas (ADR-0003); ``/api/status`` returns a validated
  ``StructuredResult``.

This module makes no outbound network calls; egress remains disabled until explicitly enabled.
"""

from __future__ import annotations

import hmac
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from personalai_backend import __version__
from personalai_backend.composition import Bootstrap, bootstrap
from personalai_contracts.ports import ChatMessage, GenerationRequest, ModelProvider, Role
from personalai_contracts.schemas import ErrorInfo, StructuredResult
from personalai_core import CoreConfig
from personalai_core.registries import Registries


class HealthResponse(BaseModel):
    """Liveness response."""

    status: str = "ok"


class VersionResponse(BaseModel):
    """Service identity."""

    name: str
    version: str


class ChatMessageIn(BaseModel):
    """A chat message from the client."""

    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """A chat request. Stateless: the client sends the full message history (persistence is M3)."""

    messages: list[ChatMessageIn]
    model: str | None = None
    # Default reasoning off for clean chat; clients can opt into a model's thinking trace.
    think: bool | None = False


def _require_token(request: Request, authorization: str | None = Header(default=None)) -> None:
    """Bearer-token auth dependency (constant-time compare); fail-closed if unconfigured."""
    config: CoreConfig = request.app.state.config
    expected = config.auth_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth token not configured",
        )
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    presented = authorization[len(prefix) :]
    if not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def create_app(boot: Bootstrap | None = None) -> FastAPI:
    """Build the FastAPI app from the assembled wiring."""
    boot = boot or bootstrap()
    # Refuse to expose a non-loopback bind without an auth token (THREAT-MODEL: fail-closed).
    if boot.config.bind_host not in _LOOPBACK_HOSTS and not boot.config.auth_token:
        raise RuntimeError(
            f"refusing to bind non-loopback host {boot.config.bind_host!r} without an auth token; "
            "set PERSONALAI_AUTH_TOKEN or bind to loopback"
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        # Close any providers that hold network clients (e.g. the Ollama httpx client).
        for name in boot.registries.model_providers.names():
            provider = boot.registries.model_providers.get(name)
            aclose = getattr(provider, "aclose", None)
            if aclose is not None:
                await aclose()

    app = FastAPI(title="PersonalAI Backend", version=__version__, lifespan=lifespan)
    app.state.bootstrap = boot
    app.state.config = boot.config

    # CORS restricted to the configured (loopback) origins: enables the browser SPA while still
    # acting as an origin allowlist. The bearer token remains the real auth control; credentials
    # (cookies) are not used. Non-browser clients send no Origin and are unaffected.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(boot.config.allowed_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/version", response_model=VersionResponse)
    def version() -> VersionResponse:
        return VersionResponse(name="personalai-backend", version=__version__)

    @app.get("/api/status", response_model=StructuredResult, dependencies=[Depends(_require_token)])
    def api_status() -> StructuredResult:
        config: CoreConfig = app.state.config
        return StructuredResult(
            ok=True,
            data={
                "model_provider": config.model_provider,
                "vector_repository": config.vector_repository,
                "bind_host": config.bind_host,
                "egress_enabled": config.egress_enabled,
            },
        )

    @app.get("/api/models", response_model=StructuredResult, dependencies=[Depends(_require_token)])
    async def api_models() -> StructuredResult:
        config: CoreConfig = app.state.config
        registries: Registries = app.state.bootstrap.registries
        provider: ModelProvider = registries.model_providers.get(config.model_provider)
        models = [
            {
                "name": d.name,
                "local": d.local,
                "capabilities": {
                    "text": d.capabilities.text,
                    "vision": d.capabilities.vision,
                    "embeddings": d.capabilities.embeddings,
                    "tool_calling": d.capabilities.tool_calling,
                    "structured_output": d.capabilities.structured_output,
                    "thinking": d.capabilities.thinking,
                    "max_context_tokens": d.capabilities.max_context_tokens,
                },
            }
            for d in await provider.list_models()
        ]
        return StructuredResult(
            ok=True, data={"default_model": config.default_model, "models": models}
        )

    @app.post("/api/chat", dependencies=[Depends(_require_token)])
    async def chat(req: ChatRequest) -> StreamingResponse:
        config: CoreConfig = app.state.config
        registries: Registries = app.state.bootstrap.registries
        provider: ModelProvider = registries.model_providers.get(config.model_provider)
        generation = GenerationRequest(
            messages=[ChatMessage(Role(m.role), m.content) for m in req.messages],
            model=req.model or config.default_model,
            think=req.think,
        )

        async def event_stream() -> AsyncIterator[bytes]:
            try:
                async for chunk in provider.stream(generation):
                    payload = {
                        "delta": chunk.delta,
                        "thinking": chunk.thinking,
                        "done": chunk.done,
                        "finish_reason": chunk.finish_reason,
                    }
                    yield f"data: {json.dumps(payload)}\n\n".encode()
            except Exception as exc:  # noqa: BLE001 - surface as a structured error event (fail-closed)
                error = StructuredResult(
                    ok=False, error=ErrorInfo(code="E_GENERATION", message=str(exc))
                )
                yield f"event: error\ndata: {error.model_dump_json()}\n\n".encode()

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app
