"""PersonalAI backend app: FastAPI composition root.

Outermost Python layer (ADR-0001). Depends on ``personalai_core`` and ``personalai_contracts``.
M0-4 adds the composition root (:func:`bootstrap`); the FastAPI app is added in M0-5.
"""

from personalai_backend.composition import Bootstrap, bootstrap, register_adapters

__version__ = "0.0.0"

__all__ = ["Bootstrap", "__version__", "bootstrap", "register_adapters"]
