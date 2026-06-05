"""PersonalAI core: orchestration, gateway, security engine, validation, registries.

Depends only on ``personalai_contracts`` (ADR-0001). Must not import the backend app
or any concrete adapter. Registries and DI wiring are added in M0-4.
"""

__version__ = "0.0.0"
