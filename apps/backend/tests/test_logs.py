"""Application log buffer + /api/logs endpoint (no DB needed)."""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from personalai_backend import create_app
from personalai_backend.composition import bootstrap
from personalai_backend.logbuffer import RingBufferHandler
from personalai_core import CoreConfig

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _client() -> TestClient:
    return TestClient(create_app(bootstrap(config=CoreConfig(auth_token=TOKEN))))


def test_logs_endpoint_returns_recent_app_logs() -> None:
    client = _client()  # installs the buffer
    logging.getLogger("personalai_backend.demo").warning("hello-from-test")
    logs = client.get("/api/logs", headers=AUTH).json()["data"]["logs"]
    assert any(entry["message"] == "hello-from-test" for entry in logs)
    entry = next(e for e in logs if e["message"] == "hello-from-test")
    assert entry["level"] == "WARNING"
    assert entry["logger"] == "personalai_backend.demo"


def test_logs_require_token() -> None:
    assert _client().get("/api/logs").status_code == 401


def test_buffer_keeps_personalai_and_warnings_drops_library_noise() -> None:
    handler = RingBufferHandler(capacity=10)

    def _emit(name: str, level: int, msg: str) -> None:
        handler.emit(logging.LogRecord(name, level, __file__, 0, msg, args=None, exc_info=None))

    _emit("personalai_core.x", logging.INFO, "kept-app")
    _emit("httpx", logging.INFO, "dropped-noise")
    _emit("uvicorn.access", logging.WARNING, "kept-warning")
    messages = [r["message"] for r in handler.records]
    assert "kept-app" in messages
    assert "kept-warning" in messages
    assert "dropped-noise" not in messages


def test_install_is_idempotent_and_sets_level() -> None:
    from personalai_backend.logbuffer import LOG_BUFFER, install

    root = logging.getLogger()
    had = LOG_BUFFER in root.handlers
    saved = root.level
    try:
        if LOG_BUFFER in root.handlers:
            root.removeHandler(LOG_BUFFER)
        root.setLevel(logging.NOTSET)
        install()  # not present + level unset -> add + raise to INFO
        assert LOG_BUFFER in root.handlers
        assert root.level == logging.INFO
        install()  # already present -> no-op
        assert root.handlers.count(LOG_BUFFER) == 1

        root.removeHandler(LOG_BUFFER)
        root.setLevel(logging.DEBUG)
        install()  # present-after-add, level already <= INFO -> level left as-is
        assert root.level == logging.DEBUG
    finally:
        root.setLevel(saved)
        if had and LOG_BUFFER not in root.handlers:
            root.addHandler(LOG_BUFFER)


def test_buffer_respects_capacity() -> None:
    handler = RingBufferHandler(capacity=2)
    for i in range(5):
        handler.emit(
            logging.LogRecord("personalai.x", logging.INFO, __file__, 0, f"m{i}", None, None)
        )
    assert [r["message"] for r in handler.records] == ["m3", "m4"]
