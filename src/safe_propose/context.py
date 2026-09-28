"""The ``ctx`` object passed to every tx definition.

``ctx`` is the second argument every ``@txn`` function receives. It is the engine's
read-only view of the target network plus a contract factory and a dict of
consuming-repo constants. Keeping it a frozen dataclass means a definition cannot
mutate engine state; it can only *read* (``ctx.contract(...)``, ``ctx.const[...]``) and
queue calls onto the ``batch``.

Contract (see ``docs/ARCHITECTURE.md`` → "The tx-definition contract"):

    @txn
    def katana_caps(batch, ctx):
        vault  = ctx.contract(ctx.const["yearn_katana_vaults"]["og-usdc"])
        morpho = ctx.contract(vault.MORPHO())
        batch.add(vault.submitCap, morpho.idToMarketParams(MARKET), CAP)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

# Resolves an address (+ optional ABI) to an Ape Contract instance. Supplied by the
# engine once a network connection exists; tx definitions never construct it.
ContractFactory = Callable[..., Any]


@dataclass(frozen=True)
class Ctx:
    """Read-only context handed to a tx definition.

    Attributes:
        network: the resolved network name (e.g. ``"katana"``).
        chain_id: the numeric chain id (e.g. ``747474`` for Katana).
        safe_address: the Safe this batch targets, checksummed.
        const: constants loaded from the consuming repo (addresses, market ids, caps).
            Exposed as a read-only mapping so definitions stay declarative and cannot
            mutate shared state.
        _contract: the engine-provided contract factory. Use ``ctx.contract(...)``.
    """

    network: str
    chain_id: int
    safe_address: str
    const: MappingProxyType[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    _contract: ContractFactory | None = field(default=None, repr=False)

    def contract(self, address: str, abi: Any = None) -> Any:
        """Return an Ape ``Contract`` for ``address`` (ABI auto-resolved if omitted).

        Method handlers (view and state-changing) expose ``.selector`` (4-byte id as
        ``HexBytes``) alongside Ape's ``encode_input(*args)``, so definitions can build
        ``submit(abi.encodeCall(...))`` calldata. ABI resolution is delegated to the
        engine's factory (ape-etherscan or a local interface directory). Raises if the
        engine did not wire a factory (e.g. constructed outside a connected context).
        """
        if self._contract is None:
            raise RuntimeError(
                "ctx.contract() is unavailable: no contract factory was provided. "
                "This Ctx was built without a live network connection."
            )
        return self._contract(address, abi)


def make_const(mapping: dict[str, Any] | None) -> MappingProxyType[str, Any]:
    """Wrap a plain dict of constants in a read-only view for ``Ctx.const``."""
    return MappingProxyType(dict(mapping or {}))
