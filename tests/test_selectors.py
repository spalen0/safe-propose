"""``.selector`` on real Ape method handlers returned by ``ctx.contract`` (#25)."""

from __future__ import annotations

import pytest
from ape.api.address import BaseAddress
from ape.contracts.base import ContractInstance
from ethpm_types import ContractType

from safe_propose import runtime
from safe_propose.selectors import install_method_selector

VAULT = "0x2222222222222222222222222222222222222222"
GATE = "0x3333333333333333333333333333333333333333"
SET_RECEIVE_SHARES_GATE = bytes.fromhex("2cb19f98")
ABDICATE = bytes.fromhex("b2e32848")
SUBMIT = bytes.fromhex("ef7fa71b")


def _fn(name: str, *inputs: str, mutability: str = "nonpayable", outputs=()) -> dict:
    return {
        "type": "function",
        "name": name,
        "stateMutability": mutability,
        "inputs": [{"name": f"a{i}", "type": t} for i, t in enumerate(inputs)],
        "outputs": [{"name": "", "type": t} for t in outputs],
    }


VAULT_TYPE = ContractType.model_validate(
    {
        "contractName": "VaultV2",
        "abi": [
            _fn("setReceiveSharesGate", "address"),
            _fn("abdicate", "bytes4"),
            _fn("submit", "bytes"),
            _fn("abdicated", "bytes4", mutability="view", outputs=("bool",)),
            _fn("setGate", "address"),
            _fn("foo", "uint256"),
            _fn("foo", "address"),
        ],
    }
)


@pytest.fixture
def vault() -> ContractInstance:
    install_method_selector()
    return ContractInstance(VAULT, contract_type=VAULT_TYPE)


def test_selector_on_view_and_nonpayable_handlers(vault):
    assert vault.setReceiveSharesGate.selector == SET_RECEIVE_SHARES_GATE
    assert vault.abdicate.selector == ABDICATE
    assert vault.abdicated.selector == keccak_selector("abdicated(bytes4)")


def test_selector_rejects_overloads(vault):
    with pytest.raises(ValueError, match="2 overloads"):
        _ = vault.foo.selector


def test_install_is_idempotent(vault):
    install_method_selector()
    assert vault.submit.selector == SUBMIT


def test_encode_submit_abdicate_on_connected_ecosystem(vault):
    """Morpho V2: submit(abi.encodeCall(abdicate, (setReceiveSharesGate.selector)))."""
    from ape import networks

    with networks.ethereum.local.use_provider("test"):
        selector = vault.setReceiveSharesGate.selector
        data = vault.abdicate.encode_input(selector)
        queued = vault.submit.encode_input(data)

        assert selector == vault.setReceiveSharesGate.encode_input(GATE)[:4]
        assert data == ABDICATE + SET_RECEIVE_SHARES_GATE + b"\x00" * 28
        assert queued[:4] == SUBMIT
        assert vault.submit.decode_input(queued)[1] == {"a0": data}
        # The contract itself still converts to an address when passed as an argument.
        assert vault.setGate.encode_input(vault)[-20:] == bytes.fromhex(VAULT[2:])


def test_contract_factory_returns_real_contract_instance(monkeypatch, vault):
    import ape

    monkeypatch.setattr(ape, "Contract", lambda address, abi=None, **kw: vault, raising=False)
    contract = runtime._contract_factory()(VAULT)

    assert contract is vault
    assert isinstance(contract, BaseAddress)
    assert str(contract) == VAULT
    assert contract == VAULT
    assert contract.submit.selector == SUBMIT


def keccak_selector(signature: str) -> bytes:
    from eth_utils import keccak

    return keccak(text=signature)[:4]
