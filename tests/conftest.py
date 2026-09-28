"""Shared fixtures. Keeps the @txn registry clean between tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from safe_propose.registry import clear_registry

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _clean_registry():
    """Each test starts and ends with an empty registry."""
    clear_registry()
    yield
    clear_registry()


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
