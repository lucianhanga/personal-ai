"""Smoke tests: the backend package imports and sits at the top of the layering."""

import personalai_backend


def test_package_imports() -> None:
    assert personalai_backend is not None


def test_has_version() -> None:
    assert isinstance(personalai_backend.__version__, str)
    assert personalai_backend.__version__
