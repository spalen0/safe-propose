"""4-byte ``.selector`` on Ape contract method handlers.

Ape's ``ContractCallHandler`` / ``ContractTransactionHandler`` have ``encode_input`` but
no selector, which ported Brownie curator scripts need for timelocked calls such as
``vault.submit(vault.abdicate.encode_input(vault.setReceiveSharesGate.selector))``.

The property is installed once on Ape's ``ContractMethodHandler`` base class rather than
by wrapping contracts, so ``ctx.contract`` keeps returning a real ``ContractInstance``
(address conversion, ``str``/``==``, raw calls and ``isinstance`` checks all unchanged).
Ape is imported lazily so importing this module stays cheap.
"""

from __future__ import annotations

from typing import Any

from eth_utils import keccak
from hexbytes import HexBytes


def method_selector(handler: Any) -> HexBytes:
    """Return the 4-byte selector of a non-overloaded Ape method handler.

    Uses the connected ecosystem's ``get_method_selector`` (the same source as
    ``encode_input``), falling back to ``keccak(signature)[:4]`` when no provider is
    connected.

    Raises:
        ValueError: if the method is overloaded; pick one with ``encode_input(*args)[:4]``.
    """
    from ape.exceptions import ProviderNotConnectedError

    abis = handler.abis
    if len(abis) != 1:
        signatures = ", ".join(abi.selector for abi in abis)
        raise ValueError(
            f"{handler!r} has {len(abis)} overloads ({signatures}); "
            "use encode_input(*args)[:4] to pick one"
        )
    abi = abis[0]
    try:
        return HexBytes(handler.provider.network.ecosystem.get_method_selector(abi))
    except ProviderNotConnectedError:
        return HexBytes(keccak(text=abi.selector)[:4])


def install_method_selector() -> None:
    """Add ``.selector`` to every Ape method handler (idempotent; never shadows Ape's own)."""
    from ape.contracts.base import ContractMethodHandler

    if not hasattr(ContractMethodHandler, "selector"):
        ContractMethodHandler.selector = property(  # type: ignore[attr-defined]
            method_selector, doc="4-byte method id as ``HexBytes`` (e.g. ``0x2cb19f98``)."
        )
