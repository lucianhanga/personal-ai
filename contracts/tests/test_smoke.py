"""Smoke tests: the contracts package is importable and exposes a version."""

import personalai_contracts


def test_package_imports() -> None:
    assert personalai_contracts is not None


def test_has_version() -> None:
    assert isinstance(personalai_contracts.__version__, str)
    assert personalai_contracts.__version__
