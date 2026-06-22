"""Systems-under-test: the seam between a task and the thing being benchmarked.

Phase 1 ships :class:`PersonalIAAdapter`, which drives the local backend through the non-streaming
``/api/v1/assistant/execute`` endpoint. Frontier-model adapters (raw + tool-equipped) implement the
same :class:`SystemUnderTest` protocol and slot in for Phase 2.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, Field


class RunResult(BaseModel):
    """A system-under-test's normalized response for one task run."""

    answer: str = ""
    trace: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0
    config_used: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


@runtime_checkable
class SystemUnderTest(Protocol):
    """Anything the runner can ask to answer a task under a set of per-run overrides."""

    name: str

    def run(
        self, messages: Sequence[Mapping[str, str]], overrides: Mapping[str, Any]
    ) -> RunResult: ...


class PersonalIAAdapter:
    """Drive personalIA via ``POST /api/v1/assistant/execute`` (one synchronous call per run)."""

    name = "personalia"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8765",
        token: str | None = None,
        timeout: float = 600.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._token = token if token is not None else os.environ.get("PERSONALAI_AUTH_TOKEN")
        self._timeout = timeout

    def run(self, messages: Sequence[Mapping[str, str]], overrides: Mapping[str, Any]) -> RunResult:
        payload: dict[str, Any] = {"messages": list(messages), **dict(overrides)}
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        try:
            resp = httpx.post(
                f"{self._base}/api/v1/assistant/execute",
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            return RunResult(
                error=f"request failed (is the backend running at {self._base}?): {exc}"
            )
        if resp.status_code != 200:
            return RunResult(error=f"HTTP {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        if not body.get("ok", False):
            message = (body.get("error") or {}).get("message", "execute returned not-ok")
            return RunResult(error=str(message))
        data = body.get("data") or {}
        return RunResult(
            answer=str(data.get("answer", "")),
            trace=list(data.get("trace", [])),
            tool_calls=list(data.get("tool_calls", [])),
            usage=dict(data.get("usage", {})),
            latency_ms=float(data.get("latency_ms", 0.0)),
            config_used=dict(data.get("config_used", {})),
        )
