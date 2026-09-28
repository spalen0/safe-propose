"""The ``@txn`` decorator and its module-level registry.

This lives in its own module (not ``loader.py``) so that a consuming repo's
``scripts/safe_txs.py`` can ``from safe_propose import txn`` without dragging in Ape or any
network dependency at import time. The registry is keyed by function name; redefining a
name is an error (the contract is *append-only* — see ``docs/ARCHITECTURE.md``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from safe_propose.context import Ctx

# A tx definition: takes an ape-safe batch and an engine-provided ctx, queues calls.
TxnFn = Callable[[object, "Ctx"], None]

_REGISTRY: dict[str, TxnFn] = {}


class DuplicateDefinitionError(ValueError):
    """Raised when two ``@txn`` functions register under the same name."""


class UnknownDefinitionError(KeyError):
    """Raised when a requested ``--fn`` name is not registered."""

    def __init__(self, name: str, available: list[str]) -> None:
        self.name = name
        self.available = available
        listing = ", ".join(available) if available else "(none registered)"
        super().__init__(f"unknown transaction function {name!r}. Available: {listing}")


def txn(fn: TxnFn) -> TxnFn:
    """Register ``fn`` as a transaction definition under its function name.

    Returns the function unchanged so it remains directly callable/testable.
    """
    name = fn.__name__
    if name in _REGISTRY:
        raise DuplicateDefinitionError(
            f"transaction function {name!r} is already registered; "
            "names are append-only and must be unique"
        )
    _REGISTRY[name] = fn
    return fn


def get_definition(name: str) -> TxnFn:
    """Return the registered tx function ``name`` or raise with the valid names."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise UnknownDefinitionError(name, registered_names()) from None


def registered_names() -> list[str]:
    """Return the sorted list of currently-registered tx function names."""
    return sorted(_REGISTRY)


def clear_registry() -> None:
    """Drop all registrations. Intended for tests and repeated loads."""
    _REGISTRY.clear()
