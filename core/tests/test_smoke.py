"""Smoke tests: the core package imports and may depend on contracts (inward only)."""

import personalai_contracts
import personalai_core


def test_package_imports() -> None:
    assert personalai_core is not None


def test_has_version() -> None:
    assert isinstance(personalai_core.__version__, str)
    assert personalai_core.__version__


def test_core_may_use_contracts() -> None:
    # Dependency direction points inward to contracts (ADR-0001).
    assert personalai_contracts.__version__
