"""Unit tests for loader.py (TEST_PLAN Layer 1)."""

from __future__ import annotations

import pytest

from safe_propose.loader import DEFAULT_TXS_FILE, load_constants, load_definitions, resolve
from safe_propose.registry import UnknownDefinitionError


def test_load_definitions_registers(fixtures_dir):
    names = load_definitions(fixtures_dir / "sample_txs.py")
    assert names == ["alpha", "beta"]
    assert resolve("alpha").__name__ == "alpha"


def test_load_missing_file_raises_actionable():
    with pytest.raises(FileNotFoundError) as exc:
        load_definitions("/nonexistent/safe_txs.py")
    assert "safe_txs.py" in str(exc.value)
    assert "--txs-file" in str(exc.value)


def test_default_path_is_scripts_safe_txs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert DEFAULT_TXS_FILE == "scripts/safe_txs.py"
    with pytest.raises(FileNotFoundError) as exc:
        load_definitions()
    msg = str(exc.value)
    assert "scripts/safe_txs.py" in msg
    assert "--txs-file" in msg


def test_duplicate_in_module_raises_on_import(fixtures_dir):
    from safe_propose.registry import DuplicateDefinitionError

    with pytest.raises(DuplicateDefinitionError):
        load_definitions(fixtures_dir / "dupe_txs.py")


def test_resolve_unknown_lists_available(fixtures_dir):
    load_definitions(fixtures_dir / "sample_txs.py")
    with pytest.raises(UnknownDefinitionError) as exc:
        resolve("nope")
    assert "alpha" in str(exc.value)
    assert "beta" in str(exc.value)


def test_load_constants_picks_only_data(fixtures_dir):
    const = load_constants(fixtures_dir / "sample_constants.py")
    assert const["AMOUNT"] == 6_000_000
    assert const["VAULTS"]["og-usdc"].startswith("0x")
    assert "MARKET" in const
    # modules, callables, and dunder/underscore names are excluded.
    assert "os" not in const
    assert "helper" not in const
    assert "_PRIVATE" not in const


def test_load_constants_none_is_empty():
    assert load_constants(None) == {}
    assert load_constants("/nonexistent/constants.py") == {}
