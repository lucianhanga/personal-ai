"""PersonalAI stable core API: ports, schemas, and message/tool contracts.

This is the innermost layer of the hexagonal architecture (ADR-0001). It must not import any
other PersonalAI package. Ports are defined in ``personalai_contracts.ports`` (M0-2); base
schemas arrive in M0-3. In-memory reference fakes for every port live in
``personalai_contracts.testing`` for use in tests across packages.
"""

from personalai_contracts import ports, schemas

__version__ = "0.0.0"

__all__ = ["__version__", "ports", "schemas"]
