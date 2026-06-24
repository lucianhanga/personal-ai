"""PersonalAI backend app: FastAPI composition root.

Outermost Python layer (ADR-0001). Depends on ``personalai_core`` and ``personalai_contracts``.
M0-4 added the composition root (:func:`bootstrap`); M0-5 adds the loopback FastAPI app
(:func:`create_app`).
"""

__version__ = "0.8.3"

# Imported after __version__ is defined (app.py reads it) to avoid a circular import.
from personalai_backend.app import create_app
from personalai_backend.composition import Bootstrap, bootstrap, register_adapters

__all__ = [
    "Bootstrap",
    "__version__",
    "bootstrap",
    "create_app",
    "register_adapters",
]
