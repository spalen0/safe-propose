"""Unit tests for engine helpers that don't need a network."""

from __future__ import annotations

import pytest
from eth_abi import encode
from web3.exceptions import ContractLogicError, Web3RPCError

from safe_propose.engine import _revert_reason, simulate_trace


class _Exc(Exception):
    """Stand-in for a web3 call error whose str carries the revert data."""


def test_revert_reason_decodes_error_string():
    data = "0x08c379a0" + encode(["string"], ["insufficient balance"]).hex()
    reason = _revert_reason(_Exc(f"execution reverted: {data}"))
    assert reason == '"insufficient balance"'


def test_revert_reason_names_known_custom_error():
    reason = _revert_reason(_Exc("('0xe450d38c0000', '0xe450d38c0000')"))
    assert reason == "ERC20InsufficientBalance"


def test_revert_reason_reports_unknown_selector():
    reason = _revert_reason(_Exc("revert 0xdeadbeef0000"))
    assert reason == "custom error 0xdeadbeef"


def test_revert_reason_plain_message():
    reason = _revert_reason(_Exc("nonce too low"))
    assert reason == "nonce too low"


# --- simulate_trace (per-call trace) ----------------------------------------------------
#
# All mocked: a fake batch (just `.calls`), a fake Safe exposing `provider.web3.eth`, and
# an injected `contract_lookup`. No network. Covers decode + gas, revert, and no-ABI.

_CALLDATA = bytes.fromhex("12345678") + b"\x00" * 32  # 4-byte selector + a word of args


class _Eth:
    def __init__(self, *, revert_targets=(), gas=62_870):
        self._revert = set(revert_targets)
        self._gas = gas
        self.last_call = None
        self.last_estimate = None

    def call(self, tx, block_identifier=None, state_override=None, ccip_read_enabled=None):
        self.last_call = (tx, block_identifier, state_override)
        if tx["to"] in self._revert:
            raise ContractLogicError("execution reverted", data="0xdeadbeef00000000")
        return b""

    def estimate_gas(self, tx, block_identifier=None, state_override=None):
        self.last_estimate = (tx, block_identifier, state_override)
        return self._gas


class _Safe:
    def __init__(self, eth, address="0xSAFE"):
        self.address = address
        self.provider = type("P", (), {"web3": type("W", (), {"eth": eth})()})()


class _FakeContract:
    def __init__(self, name, signature, args_dict):
        self.contract_type = type("CT", (), {"name": name})()
        self._sig = signature
        self._args = args_dict

    def decode_input(self, calldata):
        return self._sig, self._args


def _batch(target="0xVault", value=0):
    return type("B", (), {"calls": [{"target": target, "callData": _CALLDATA, "value": value}]})()


class _DevProvider:
    """Fake Anvil RPC: records calls; ``fail`` names methods that return an RPC error."""

    def __init__(self, fail=()):
        self.fail = set(fail)
        self.requests = []

    def make_request(self, method, params):
        self.requests.append((method, params))
        if method in self.fail:
            return {"error": {"message": f"{method} unsupported"}}
        return {"result": "0x1" if method == "evm_snapshot" else True}


class _ApplyingEth(_Eth):
    """Credit-then-spend: calls to 0xSpend revert until a call to 0xCredit was applied."""

    def __init__(self):
        super().__init__()
        self.credited = False
        self.sent = []

    def call(self, tx, block_identifier=None, state_override=None, ccip_read_enabled=None):
        if tx["to"] == "0xSpend" and not self.credited:
            raise ContractLogicError("execution reverted", data="0xdeadbeef00000000")
        return b""

    def send_transaction(self, tx):
        self.sent.append(tx)
        self.credited = self.credited or tx["to"] == "0xCredit"
        return b"\x01" * 32

    def wait_for_transaction_receipt(self, tx_hash, timeout=None):
        return {"status": 1}


def _dev_safe(eth, provider):
    safe = _Safe(eth)
    safe.provider.web3.provider = provider
    return safe


def _credit_spend_batch():
    calls = [{"target": t, "callData": _CALLDATA, "value": 0} for t in ("0xCredit", "0xSpend")]
    return type("B", (), {"calls": calls})()


def test_simulate_trace_applies_calls_in_order_on_dev_node():
    eth, provider = _ApplyingEth(), _DevProvider()
    sims = simulate_trace(_credit_spend_batch(), _dev_safe(eth, provider), contract_lookup=None)

    assert [c.success for c in sims] == [True, True]
    assert [tx["to"] for tx in eth.sent] == ["0xCredit", "0xSpend"]
    assert all(tx["from"] == "0xSAFE" and tx["gasPrice"] == 0 for tx in eth.sent)
    methods = [m for m, _ in provider.requests]
    assert methods[:2] == ["evm_snapshot", "anvil_impersonateAccount"]
    assert methods.count("anvil_setBalance") == 2
    assert methods.count("anvil_setNextBlockBaseFeePerGas") == 2
    assert provider.requests[-1] == ("evm_revert", ["0x1"])  # fork restored at the end


def test_simulate_trace_does_not_state_override_native_transfers():
    eth = _Eth()
    simulate_trace(_batch(value=1), _Safe(eth), contract_lookup=lambda _: None)

    assert eth.last_call is not None
    tx, _block, override = eth.last_call
    assert tx["value"] == 1
    assert override is None


def test_simulate_trace_does_not_set_balance_for_native_transfers():
    eth, provider = _ApplyingEth(), _DevProvider()
    batch = type("B", (), {"calls": [{"target": "0xCredit", "callData": _CALLDATA, "value": 1}]})()
    simulate_trace(batch, _dev_safe(eth, provider), contract_lookup=None)

    methods = [m for m, _ in provider.requests]
    assert "anvil_setBalance" not in methods
    assert methods.count("anvil_setNextBlockBaseFeePerGas") == 1


def test_simulate_trace_does_not_apply_failed_calls():
    eth, provider = _ApplyingEth(), _DevProvider()
    batch = type("B", (), {"calls": list(reversed(_credit_spend_batch().calls))})()
    sims = simulate_trace(batch, _dev_safe(eth, provider), contract_lookup=None)

    assert [c.success for c in sims] == [False, True]  # spend before credit really fails
    assert [tx["to"] for tx in eth.sent] == ["0xCredit"]
    assert provider.requests[-1] == ("evm_revert", ["0x1"])


def test_simulate_trace_falls_back_to_independent_calls_without_dev_rpc():
    eth, provider = _ApplyingEth(), _DevProvider(fail={"evm_snapshot"})
    sims = simulate_trace(_credit_spend_batch(), _dev_safe(eth, provider), contract_lookup=None)

    assert [c.success for c in sims] == [True, False]  # live node: same pre-state per call
    assert eth.sent == []
    assert [m for m, _ in provider.requests] == ["evm_snapshot"]


@pytest.mark.parametrize("unsupported", ["evm_snapshot", "impersonate"])
def test_simulate_trace_require_ordered_fails_closed(unsupported):
    fail = (
        {"evm_snapshot"}
        if unsupported == "evm_snapshot"
        else {"anvil_impersonateAccount", "hardhat_impersonateAccount"}
    )
    eth, provider = _ApplyingEth(), _DevProvider(fail=fail)
    with pytest.raises(RuntimeError, match="refusing to fall back"):
        simulate_trace(
            _credit_spend_batch(),
            _dev_safe(eth, provider),
            contract_lookup=None,
            require_ordered=True,
        )
    assert eth.sent == []


def test_simulate_trace_reports_failed_apply_and_still_restores():
    class RevertingApplyEth(_ApplyingEth):
        def wait_for_transaction_receipt(self, tx_hash, timeout=None):
            return {"status": 0}

    eth, provider = RevertingApplyEth(), _DevProvider()
    sims = simulate_trace(_credit_spend_batch(), _dev_safe(eth, provider), contract_lookup=None)

    assert not sims[0].success and "apply failed" in sims[0].error
    assert provider.requests[-1] == ("evm_revert", ["0x1"])


def test_simulate_trace_decodes_and_estimates_gas():
    safe = _Safe(_Eth(gas=62_870))
    contract = _FakeContract(
        "MetaMorphoV1_1", "submitCap(bytes32,uint256)", {"p": "0xee7d", "c": 6_000_000}
    )
    sims = simulate_trace(_batch(), safe, contract_lookup=lambda _addr: contract)

    assert len(sims) == 1
    c = sims[0]
    assert (c.index, c.contract_name, c.method) == (1, "MetaMorphoV1_1", "submitCap")
    assert c.args == ("0xee7d", 6_000_000)
    assert c.success and c.gas == 62_870 and c.revert_reason == ""
    assert c.label == "MetaMorphoV1_1.submitCap"


def test_simulate_trace_records_revert_and_no_gas():
    safe = _Safe(_Eth(revert_targets=["0xVault"]))
    contract = _FakeContract("Vault", "submitCap(uint256)", {"c": 1})
    sims = simulate_trace(_batch(), safe, contract_lookup=lambda _addr: contract)

    c = sims[0]
    assert not c.success
    assert c.gas is None  # no estimate for a reverting call
    assert c.revert_reason == "custom error 0xdeadbeef"


def test_simulate_trace_falls_back_when_abi_unavailable():
    def _lookup(_addr):
        raise RuntimeError("no ABI for this contract")

    safe = _Safe(_Eth(gas=21_000))
    sims = simulate_trace(_batch(), safe, contract_lookup=_lookup)

    c = sims[0]
    assert c.contract_name == ""  # unknown contract
    assert c.method == "0x12345678"  # falls back to the 4-byte selector
    assert c.args == ()
    assert c.success and c.gas == 21_000  # the call itself still simulates
    assert c.label == "0x12345678"


def test_simulate_trace_does_not_charge_the_safe_for_gas():
    class UnfundedSafeEth(_Eth):
        def call(self, tx, block_identifier=None, state_override=None, ccip_read_enabled=None):
            # Mimic Anvil when gasPrice is non-zero and the Safe is broke: without a
            # balance state_override the node rejects the eth_call.
            funded = bool((state_override or {}).get(tx.get("from"), {}).get("balance"))
            if tx.get("gasPrice") not in (0, "0x0", None) and not funded:
                raise Web3RPCError("Insufficient funds for gas * price + value")
            return super().call(tx, block_identifier, state_override, ccip_read_enabled)

    eth = UnfundedSafeEth()
    # Force a non-zero gasPrice through _simulate_call to prove the override path works.
    from safe_propose import engine as eng

    original = eng._simulate_call

    def _priced(eth_api, tx):
        return original(eth_api, {**tx, "gasPrice": 10**9})

    eng._simulate_call = _priced  # type: ignore[assignment]
    try:
        sims = simulate_trace(_batch(), _Safe(eth), contract_lookup=lambda _: None)
    finally:
        eng._simulate_call = original  # type: ignore[assignment]

    assert sims[0].success
    assert eth.last_call is not None and eth.last_call[2] is not None
    assert eth.last_call[2]["0xSAFE"]["balance"] == hex(10**18)


@pytest.mark.parametrize(
    "error",
    [Web3RPCError("Insufficient funds for gas * price + value"), TimeoutError("RPC timeout")],
)
def test_simulate_trace_distinguishes_rpc_error_from_revert(error):
    class UnavailableEth(_Eth):
        def call(self, tx, block_identifier=None, state_override=None, ccip_read_enabled=None):
            raise error

    sims = simulate_trace(_batch(), _Safe(UnavailableEth()), contract_lookup=lambda _: None)
    assert not sims[0].success
    assert sims[0].revert_reason == ""
    assert str(error) in sims[0].error


def test_simulate_trace_redacts_rpc_urls_in_errors():
    secret = "https://user:pass@rpchostkey.rpc.example/v2/supersecretkey"

    class UrlEth(_Eth):
        def call(self, tx, block_identifier=None, state_override=None, ccip_read_enabled=None):
            raise Web3RPCError(f"401 Client Error for url: {secret}")

        def estimate_gas(self, tx, block_identifier=None, state_override=None):
            raise TimeoutError(f"eth_estimateGas failed for {secret}")

    sims = simulate_trace(_batch(), _Safe(UrlEth()), contract_lookup=lambda _: None)
    assert not sims[0].success
    assert secret not in sims[0].error
    assert "supersecretkey" not in sims[0].error
    assert "rpchostkey" not in sims[0].error
    assert "***url***" in sims[0].error
    assert "eth_call failed:" in sims[0].error


def test_simulate_trace_redacts_rpc_urls_in_apply_errors():
    secret = "https://svchostkey.svc.example/api?key=svcquerykey"

    class UrlApplyEth(_ApplyingEth):
        def send_transaction(self, tx):
            raise TimeoutError(f"connection to {secret} timed out")

    sims = simulate_trace(
        _credit_spend_batch(), _dev_safe(UrlApplyEth(), _DevProvider()), contract_lookup=None
    )
    assert not sims[0].success
    assert secret not in sims[0].error
    assert "svchostkey" not in sims[0].error
    assert "svcquerykey" not in sims[0].error
    assert "***url***" in sims[0].error
    assert "apply failed:" in sims[0].error


def test_simulate_trace_exposes_failed_gas_estimate():
    class NoEstimateEth(_Eth):
        def estimate_gas(self, tx, block_identifier=None, state_override=None):
            raise TimeoutError(
                "RPC timeout contacting https://rpchostkey.rpc.example/v2/supersecretkey"
            )

    sims = simulate_trace(_batch(), _Safe(NoEstimateEth()), contract_lookup=lambda _: None)
    assert sims[0].success
    assert sims[0].gas is None
    assert "RPC timeout" in sims[0].gas_error
    assert "supersecretkey" not in sims[0].gas_error
    assert "rpchostkey" not in sims[0].gas_error
    assert "***url***" in sims[0].gas_error


def test_revert_reason_redacts_before_truncating(monkeypatch):
    monkeypatch.setenv("KATANA_RPC", "https://host.example/supersecretkeypath")
    msg = "x" * 20 + "https://host.example/supersecretkeypath" + "y" * 200
    reason = _revert_reason(_Exc(msg))
    assert "supersecretkeypath" not in reason
    assert len(reason) <= 160
