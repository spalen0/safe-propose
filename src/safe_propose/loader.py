"""Load a consuming repo's tx-definition module and its optional constants.

The engine never ships transaction data. At runtime it imports the consuming repo's
``scripts/safe_txs.py`` (so the ``@txn`` functions register), then resolves ``--fn``
against the registry. Override the path with ``--txs-file``. Constants for ``ctx.const``
are loaded from a sibling ``constants.py`` (or any configured module) by reading its
module-level, non-dunder, non-callable names.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from safe_propose.registry import TxnFn, get_definition, registered_names

# Counter so repeated loads (e.g. in tests) get unique synthetic module names.
_load_counter = 0

# Consuming-repo default, relative to cwd (the repo root). Override with ``--txs-file``.
DEFAULT_TXS_FILE = "scripts/safe_txs.py"


def _import_path(path: Path, *, module_name: str) -> ModuleType:
    """Import a .py file at ``path`` under a unique synthetic module name."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot create import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so the module can import itself if needed.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def load_definitions(path: str | Path = DEFAULT_TXS_FILE) -> list[str]:
    """Import the tx-definition module at ``path`` so its ``@txn`` functions register.

    Returns the names registered after the import. Raises ``FileNotFoundError`` with an
    actionable message if the module is missing.
    """
    global _load_counter
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(
            f"tx-definition module not found at {p}. "
            f"Run from the consuming repo (default {DEFAULT_TXS_FILE}), "
            "or pass --txs-file PATH."
        )
    _load_counter += 1
    _import_path(p, module_name=f"_safe_propose_txs_{_load_counter}")
    return registered_names()


def load_constants(path: str | Path | None) -> dict[str, Any]:
    """Load constants from a module file for ``ctx.const``.

    Returns module-level names that are not dunders and not callable/module objects
    (i.e. data: addresses, market-id strings, cap ints, dicts). ``None`` or a missing
    file yields an empty dict — constants are optional.
    """
    if path is None:
        return {}
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return {}
    global _load_counter
    _load_counter += 1
    module = _import_path(p, module_name=f"_safe_propose_const_{_load_counter}")
    out: dict[str, Any] = {}
    for name, value in vars(module).items():
        if name.startswith("_"):
            continue
        if callable(value) or isinstance(value, ModuleType):
            continue
        out[name] = value
    return out


def resolve(name: str) -> TxnFn:
    """Return the registered tx function ``name`` (raises with valid names if unknown)."""
    return get_definition(name)
