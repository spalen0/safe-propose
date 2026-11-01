"""Exercise simulation against local Anvil, without a fork or external RPC."""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from web3 import Web3
from web3.exceptions import Web3RPCError

from safe_propose import engine
from safe_propose.engine import build, simulate_trace

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


# --- build-time batch state (issue #8) ------------------------------------------------
#
# A real token on local Anvil (tests/fixtures/contracts/BatchToken.sol) and a stand-in for
# ape-safe's MultiSend with the same `add` / `add_from_receipt` contract (append, return self).

_CONTRACTS = Path(__file__).parent / "fixtures" / "contracts"
TOKEN = "0x0000000000000000000000000000000000000789"
TEAM = "0x0000000000000000000000000000000000000111"
RECIPIENT = "0x0000000000000000000000000000000000000222"
_TOKEN_ABI = [
    {
        "type": "function",
        "name": "balanceOf",
        "stateMutability": "view",
        "inputs": [{"name": "", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "claimed",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "type": "function",
        "name": "mint",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "claim",
        "stateMutability": "nonpayable",
        "inputs": [],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "transfer",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
]


class _MultiSend:
    """ape-safe ``MultiSend`` stand-in: same ``calls`` shape, ``add`` returns ``self``."""

    def __init__(self):
        self.calls = []

    def add(self, call, *args, value=0):
        self.calls.append(
            {"target": call.contract.address, "value": value, "callData": call.encode_input(*args)}
        )
        return self

    def add_from_receipt(self, receipt):
        self.calls.append(
            {"target": receipt.receiver, "value": receipt.value, "callData": receipt.data}
        )
        return self


class _Method:
    """Ape method-handler stand-in: ``.contract.address`` + ``.encode_input(*args)``."""

    def __init__(self, contract, name):
        self.contract = SimpleNamespace(address=contract.address)
        self._contract = contract
        self._name = name

    def encode_input(self, *args):
        return bytes.fromhex(self._contract.encode_abi(self._name, list(args))[2:])


def _native(to):
    return SimpleNamespace(contract=SimpleNamespace(address=to), encode_input=lambda: b"")


@pytest.fixture
def chain(anvil_web3):
    """Isolate each test: snapshot before, revert after (also discards inner snapshots)."""
    snapshot = anvil_web3.provider.make_request("evm_snapshot", [])["result"]
    yield anvil_web3
    anvil_web3.provider.make_request("evm_revert", [snapshot])


@pytest.fixture
def token(chain):
    """BatchToken at TOKEN with 100 tokens on the Safe (claim pays 20 more)."""
    code = "0x" + (_CONTRACTS / "BatchToken.bin-runtime").read_text().strip()
    assert "error" not in chain.provider.make_request("anvil_setCode", [TOKEN, code])
    contract = chain.eth.contract(address=TOKEN, abi=_TOKEN_ABI)
    receipt = chain.eth.wait_for_transaction_receipt(
        contract.functions.mint(SAFE, 100).transact({"from": chain.eth.accounts[0]}), timeout=5
    )
    assert receipt["status"] == 1
    return contract


def _dev_safe(w3):
    return SimpleNamespace(address=SAFE, provider=SimpleNamespace(web3=w3), create_batch=_MultiSend)


def _claimed(token):
    return token.functions.claimed().call()


def _balance(token, who=SAFE):
    return token.functions.balanceOf(who).call()


def _transfer_amount(call):
    return int.from_bytes(call["callData"][-32:], "big")


def _split_after_claim_and_budget(token, seen):
    """The issue's example: claim (+20), budget (-80), then split what is left."""

    def definition(batch, ctx):
        batch.add(_Method(token, "claim"))
        batch.add(_Method(token, "transfer"), TEAM, 80)
        balance = _balance(token)
        seen.append(balance)
        batch.add(_Method(token, "transfer"), RECIPIENT, balance // 2)

    return definition


def test_build_reads_see_earlier_adds_and_preflight_starts_clean(chain, token):
    safe = _dev_safe(chain)
    block_before = chain.eth.block_number
    seen = []

    batch = build(_split_after_claim_and_budget(token, seen), None, safe)

    assert isinstance(batch, _MultiSend)  # the real batch, not the wrapper
    assert seen == [40]  # 100 + 20 - 80, not the stale 100
    assert _transfer_amount(batch.calls[-1]) == 20
    # Build-time state was rolled back: the pre-flight starts from the original balance.
    assert _balance(token) == 100 and not _claimed(token)
    assert chain.eth.block_number == block_before
    assert chain.eth.get_balance(SAFE) == 0

    sims = simulate_trace(batch, safe, contract_lookup=lambda _: None, require_ordered=True)
    assert [s.success for s in sims] == [True, True, True], sims
    assert _balance(token) == 100


def test_build_without_fork_state_keeps_stale_reads(chain, token, monkeypatch):
    """Regression baseline: the old behavior queues 50 and the pre-flight rejects it."""
    monkeypatch.setattr(engine, "_begin_sequential", lambda *a: None)
    safe = _dev_safe(chain)
    seen = []
    batch = build(_split_after_claim_and_budget(token, seen), None, safe)
    monkeypatch.undo()

    assert seen == [100]
    assert _transfer_amount(batch.calls[-1]) == 50
    sims = simulate_trace(batch, safe, contract_lookup=lambda _: None, require_ordered=True)
    assert [s.success for s in sims] == [True, True, False]
    assert sims[-1].revert_reason == '"insufficient balance"'


def test_build_applies_chained_adds(chain, token):
    seen = []

    def definition(batch, ctx):
        batch.add(_Method(token, "claim")).add(_Method(token, "transfer"), TEAM, 80)
        seen.append(_balance(token))

    batch = build(definition, None, _dev_safe(chain))
    assert seen == [40]
    assert len(batch.calls) == 2


def test_build_applies_pre_encoded_calldata(chain, token):
    """``batch.add(vault.submit, encoded)``-style: the appended calldata is what is applied."""
    encoded = _Method(token, "transfer").encode_input(TEAM, 30)
    raw = SimpleNamespace(contract=SimpleNamespace(address=TOKEN), encode_input=lambda d: d)
    seen = []

    def definition(batch, ctx):
        batch.add(raw, encoded)
        seen.append(_balance(token))

    build(definition, None, _dev_safe(chain))
    assert seen == [70]


def test_build_add_from_receipt_does_not_apply_again(chain, token, capsys):
    seen = []

    def definition(batch, ctx):
        # The definition already executed this call itself (Safe impersonated during build).
        chain.provider.make_request("anvil_setNextBlockBaseFeePerGas", ["0x0"])
        tx_hash = token.functions.claim().transact({"from": SAFE, "gasPrice": 0})
        receipt = chain.eth.wait_for_transaction_receipt(tx_hash, timeout=5)
        batch.add_from_receipt(
            SimpleNamespace(receiver=TOKEN, value=0, data=_Method(token, "claim").encode_input())
        )
        assert receipt["status"] == 1
        seen.append(_balance(token))

    batch = build(definition, None, _dev_safe(chain))
    assert seen == [120]
    assert len(batch.calls) == 1
    # Applying it again would hit "already claimed" and print the revert notice.
    assert "reverts on the fork" not in capsys.readouterr().err
    assert not _claimed(token)


def test_build_restores_fork_when_definition_raises(chain, token):
    def definition(batch, ctx):
        batch.add(_Method(token, "claim"))
        batch.add(_Method(token, "transfer"), TEAM, 80)
        raise ValueError("bad cap")

    with pytest.raises(ValueError, match="bad cap"):
        build(definition, None, _dev_safe(chain))

    assert _balance(token) == 100 and not _claimed(token)
    with pytest.raises(Web3RPCError):  # no longer impersonated
        chain.eth.send_transaction({"from": SAFE, "to": TEAM, "value": 0, "gasPrice": 0})


def test_build_confirmed_revert_stays_queued_and_later_adds_apply(chain, token, capsys):
    seen = []

    def definition(batch, ctx):
        batch.add(_Method(token, "transfer"), RECIPIENT, 1_000)  # reverts: only 100
        seen.append(_balance(token))
        batch.add(_Method(token, "claim"))
        seen.append(_balance(token))

    batch = build(definition, None, _dev_safe(chain))
    assert seen == [100, 120]
    assert len(batch.calls) == 2
    err = capsys.readouterr().err
    assert "call #1" in err and "reverts on the fork" in err
    assert '"insufficient balance"' in err


def test_build_aborts_on_unknown_apply_result(chain, token, monkeypatch):
    """A receipt timeout can hide an applied call; later reads would be on unknown state."""
    from web3.exceptions import TimeExhausted

    def no_receipt(*args, **kwargs):
        raise TimeExhausted("receipt not found in 10s")

    def definition(batch, ctx):
        batch.add(_Method(token, "claim"))
        pytest.fail("definition continued after an unknown apply result")

    monkeypatch.setattr(chain.eth, "wait_for_transaction_receipt", no_receipt)
    with pytest.raises(RuntimeError, match="call #1 .* unknown result"):
        build(definition, None, _dev_safe(chain))
    monkeypatch.undo()
    # The claim was mined despite the missing receipt; the snapshot still rolled it back.
    assert not _claimed(token)


@pytest.mark.parametrize("stage", ["build", "simulate_trace"])
def test_false_evm_revert_aborts(chain, token, monkeypatch, stage):
    real_begin = engine._begin_sequential

    def bad_snapshot(w3, safe_address):
        snapshot, prefix = real_begin(w3, safe_address)
        return "0xdead", prefix  # Anvil returns false for an unknown snapshot id

    monkeypatch.setattr(engine, "_begin_sequential", bad_snapshot)
    safe = _dev_safe(chain)
    with pytest.raises(RuntimeError, match="evm_revert returned False"):
        if stage == "build":
            build(lambda batch, ctx: batch.add(_Method(token, "claim")), None, safe)
        else:
            batch = _MultiSend().add(_Method(token, "claim"))
            simulate_trace(batch, safe, contract_lookup=lambda _: None)


def _set_native(w3, wei):
    assert "error" not in w3.provider.make_request("anvil_setBalance", [SAFE, hex(wei)])


def test_build_native_balance_is_real_after_zero_value_apply(chain, token):
    _set_native(chain, 5)
    seen = []

    def definition(batch, ctx):
        batch.add(_Method(token, "claim"))  # zero-value: temporary gas top-up
        seen.append(chain.eth.get_balance(SAFE))
        batch.add(_native(RECIPIENT), value=3)
        seen.append(chain.eth.get_balance(SAFE))

    build(definition, None, _dev_safe(chain))
    assert seen == [5, 2]
    assert chain.eth.get_balance(SAFE) == 5


def test_build_native_transfer_beyond_real_balance_aborts(chain, token):
    _set_native(chain, 5)

    def definition(batch, ctx):
        batch.add(_Method(token, "claim"))
        batch.add(_native(RECIPIENT), value=6)  # would pass against the fake 1 ETH top-up

    with pytest.raises(RuntimeError, match="call #2 .*Insufficient funds"):
        build(definition, None, _dev_safe(chain))
    assert chain.eth.get_balance(SAFE) == 5


@pytest.mark.parametrize(("value", "ok"), [(5, True), (6, False)])
def test_preflight_native_transfer_uses_real_balance_after_zero_value_call(chain, token, value, ok):
    _set_native(chain, 5)
    batch = _MultiSend().add(_Method(token, "claim")).add(_native(RECIPIENT), value=value)
    sims = simulate_trace(batch, _dev_safe(chain), contract_lookup=lambda _: None)
    assert [s.success for s in sims] == [True, ok], sims
    assert chain.eth.get_balance(SAFE) == 5
