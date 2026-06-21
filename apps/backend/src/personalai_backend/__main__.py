"""Run the backend: ``python -m personalai_backend`` (or ``make run-backend``).

Binds to ``CoreConfig.bind_host``/``bind_port`` (loopback by default).
"""

from __future__ import annotations

import uvicorn
from dotenv import load_dotenv

from personalai_backend.app import create_app
from personalai_backend.composition import bootstrap


def main() -> None:  # pragma: no cover - exercised by running the server, not unit tests
    # Load PERSONALAI_* settings from a local .env (as .env.example documents). load_dotenv does NOT
    # override variables already in the environment, so inline `VAR=x make run-backend` still wins,
    # and production (real env vars, no .env file) is unaffected. Only the server entrypoint loads
    # it; tests build CoreConfig explicitly and never read .env.
    load_dotenv()
    boot = bootstrap()
    app = create_app(boot)
    uvicorn.run(app, host=boot.config.bind_host, port=boot.config.bind_port)


if __name__ == "__main__":  # pragma: no cover
    main()
