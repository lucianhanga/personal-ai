"""The generic Registry: register, fail-closed lookup, duplicate protection, introspection."""

from __future__ import annotations

import pytest

from personalai_core.registry import Registry, RegistryError


def test_register_and_get() -> None:
    reg: Registry[int] = Registry("number")
    reg.register("one", 1)
    assert reg.get("one") == 1
    assert "one" in reg
    assert len(reg) == 1


def test_missing_is_fail_closed() -> None:
    reg: Registry[int] = Registry("number")
    with pytest.raises(RegistryError, match="no number registered as 'two'"):
        reg.get("two")


def test_duplicate_refused_unless_overwrite() -> None:
    reg: Registry[int] = Registry("number")
    reg.register("one", 1)
    with pytest.raises(RegistryError, match="already registered"):
        reg.register("one", 2)
    reg.register("one", 2, overwrite=True)
    assert reg.get("one") == 2


def test_names_sorted() -> None:
    reg: Registry[int] = Registry("number")
    reg.register("b", 2)
    reg.register("a", 1)
    assert reg.names() == ("a", "b")
