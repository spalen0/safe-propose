"""Exercise simulation against local Anvil, without a fork or external RPC."""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from types import SimpleNamespace

import pytest
from web3 import Web3
from web3.exceptions import Web3RPCError

from safe_propose.engine import simulate_trace

SAFE = "0x0000000000000000000000000000000000000123"
TARGET = "0x0000000000000000000000000000000000000456"


@pytest.fixture(scope="module")
def anvil_web3():
    if shutil.which("anvil") is None:
        pytest.skip("needs the anvil binary")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    proc = subprocess.Popen(
        ["anvil", "--port", str(port), "--base-fee", "1000000000"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        w3 = Web3(Web3.HTTPProvider(f"http://127.0.0.1:{port}", request_kwargs={"timeout": 2}))
        deadline = time.monotonic() + 10
        while not w3.is_connected():
            if proc.poll() is not None or time.monotonic() >= deadline:
                pytest.fail("Anvil did not start within 10s; check the installed binary")
            time.sleep(0.05)
        yield w3
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _simulate(w3, *, code, value=0):
    response = w3.provider.make_request("anvil_setCode", [TARGET, code])
    assert "error" not in response
    batch = SimpleNamespace(calls=[{"target": TARGET, "callData": b"", "value": value}])
    safe = SimpleNamespace(address=SAFE, provider=SimpleNamespace(web3=w3))
    return simulate_trace(batch, safe, contract_lookup=lambda _: None)[0]


def test_unfunded_safe_can_simulate_authorized_call(anvil_web3):
    w3 = anvil_web3
    assert w3.eth.get_balance(SAFE) == 0
    with pytest.raises(Web3RPCError, match="Insufficient funds"):
        w3.eth.call({"from": SAFE, "to": TARGET, "value": 0, "gasPrice": 10**9})
    # Only this Safe can call: PUSH20 safe; CALLER; EQ; JUMPI success; REVERT; STOP.
    code = "0x73" + SAFE[2:] + "3314601d575f5ffd5b00"
    result = _simulate(w3, code=code)
    assert result.success
    assert result.gas is not None and result.gas > 21_000
    assert not result.error and not result.gas_error
    assert w3.eth.get_balance(SAFE) == 0


def test_unfunded_safe_survives_nonzero_gas_price(anvil_web3):
    """Katana forks often keep a non-zero fee; gasPrice:0 alone is not always honored."""
    w3 = anvil_web3
    assert w3.eth.get_balance(SAFE) == 0
    code = "0x73" + SAFE[2:] + "3314601d575f5ffd5b00"
    response = w3.provider.make_request("anvil_setCode", [TARGET, code])
    assert "error" not in response

    # Force a path where a bare eth_call with gasPrice would fail.
    with pytest.raises(Web3RPCError, match="Insufficient funds"):
        w3.eth.call({"from": SAFE, "to": TARGET, "value": 0, "gasPrice": 10**9})

    batch = SimpleNamespace(calls=[{"target": TARGET, "callData": b"", "value": 0}])
    safe = SimpleNamespace(address=SAFE, provider=SimpleNamespace(web3=w3))
    # Monkeypatch simulate to send a non-zero gasPrice (as misbehaving middleware might).
    from safe_propose import engine as eng

    original = eng._simulate_call

    def _call_with_price(eth, tx):
        tx = {**tx, "gasPrice": 10**9}
        return original(eth, tx)

    eng._simulate_call = _call_with_price  # type: ignore[assignment]
    try:
        result = simulate_trace(batch, safe, contract_lookup=lambda _: None)[0]
    finally:
        eng._simulate_call = original  # type: ignore[assignment]

    assert result.success
    assert w3.eth.get_balance(SAFE) == 0


# Credit-then-spend (stand-in for withdraw-then-transfer): empty calldata stores slot0 = 1;
# any other calldata reverts unless slot0 == 1.
#   CALLDATASIZE PUSH1 0a JUMPI PUSH1 1 PUSH1 0 SSTORE STOP
#   JUMPDEST PUSH1 0 SLOAD PUSH1 14 JUMPI PUSH0 PUSH0 REVERT JUMPDEST STOP
CREDIT_SPEND = "0x36600a576001600055005b600054601457" + "5f5ffd5b00"


def test_dependent_batch_passes_in_order_and_fork_is_restored(anvil_web3):
    w3 = anvil_web3
    response = w3.provider.make_request("anvil_setCode", [TARGET, CREDIT_SPEND])
    assert "error" not in response
    credit = {"target": TARGET, "callData": b"", "value": 0}
    spend = {"target": TARGET, "callData": b"\x01", "value": 0}
    safe = SimpleNamespace(address=SAFE, provider=SimpleNamespace(web3=w3))
    block_before = w3.eth.block_number

    # The old independent check: spend against pre-state reverts.
    with pytest.raises(Exception, match="revert"):
        w3.eth.call({"from": SAFE, "to": TARGET, "data": b"\x01", "gasPrice": 0})

    sims = simulate_trace(
        SimpleNamespace(calls=[credit, spend]), safe, contract_lookup=lambda _: None
    )
    assert [s.success for s in sims] == [True, True], sims

    # Fork restored: no persisted credit, no extra blocks, Safe still unfunded.
    assert int.from_bytes(w3.eth.get_storage_at(TARGET, 0), "big") == 0
    assert w3.eth.block_number == block_before
    assert w3.eth.get_balance(SAFE) == 0

    # Wrong order still fails: spend before credit sees the real pre-state.
    sims = simulate_trace(
        SimpleNamespace(calls=[spend, credit]), safe, contract_lookup=lambda _: None
    )
    assert [s.success for s in sims] == [False, True]
    assert int.from_bytes(w3.eth.get_storage_at(TARGET, 0), "big") == 0


def test_native_value_still_requires_real_balance(anvil_web3):
    result = _simulate(anvil_web3, code="0x00", value=1)
    assert not result.success
    assert "Insufficient funds" in result.error
    assert not result.revert_reason


def test_contract_revert_still_fails_simulation(anvil_web3):
    result = _simulate(anvil_web3, code="0x60006000fd")
    assert not result.success
    assert result.revert_reason
    assert not result.error
