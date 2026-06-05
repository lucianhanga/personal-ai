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

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from personalai_backend import __version__
from personalai_backend.composition import Bootstrap, bootstrap
from personalai_contracts.schemas import StructuredResult
from personalai_core import CoreConfig


class HealthResponse(BaseModel):
    """Liveness response."""

    status: str = "ok"


class VersionResponse(BaseModel):
    """Service identity."""

    name: str
    version: str


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


def create_app(boot: Bootstrap | None = None) -> FastAPI:
    """Build the FastAPI app from the assembled wiring."""
    boot = boot or bootstrap()
    app = FastAPI(title="PersonalAI Backend", version=__version__)
    app.state.bootstrap = boot
    app.state.config = boot.config
    allowed_origins = set(boot.config.allowed_origins)

    @app.middleware("http")
    async def origin_allowlist(request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Reject browser requests whose ``Origin`` is not in the configured allowlist."""
        origin = request.headers.get("origin")
        if origin is not None and origin not in allowed_origins:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": f"origin not allowed: {origin}"},
            )
        return await call_next(request)

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

    return app
