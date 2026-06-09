"""Generic registry for adapters (ADR-0001).

A registry maps a string name to an adapter that implements a port. Registering an adapter is
the only wiring needed to expose a new capability; the core never imports a concrete adapter.
Lookups are fail-closed: an unknown name raises :class:`RegistryError`.
"""

from __future__ import annotations


class RegistryError(Exception):
    """Raised on a duplicate registration or a lookup of an unknown name."""


class Registry[T]:
    """A name -> adapter registry for a single port type."""

    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._items: dict[str, T] = {}

    def register(self, name: str, item: T, *, overwrite: bool = False) -> T:
        """Register ``item`` under ``name``. Refuses to clobber unless ``overwrite=True``."""
        if not overwrite and name in self._items:
            raise RegistryError(f"{self._kind} {name!r} is already registered")
        self._items[name] = item
        return item

    def unregister(self, name: str) -> None:
        """Remove ``name`` if present (no-op otherwise). Used for live teardown, e.g. MCP tools."""
        self._items.pop(name, None)

    def get(self, name: str) -> T:
        """Return the adapter registered as ``name`` (fail-closed if missing)."""
        try:
            return self._items[name]
        except KeyError:
            raise RegistryError(
                f"no {self._kind} registered as {name!r} "
                f"(available: {', '.join(self.names()) or 'none'})"
            ) from None

    def names(self) -> tuple[str, ...]:
        """All registered names, sorted."""
        return tuple(sorted(self._items))

    def __contains__(self, name: object) -> bool:
        return name in self._items

    def __len__(self) -> int:
        return len(self._items)
