"""Unit tests for runtime helpers that don't need a live network."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from safe_propose import runtime
from safe_propose.txservice import TxServiceEndpoint


@pytest.mark.parametrize("nonce", [0, 20])
def test_safe_onchain_nonce_uses_contract_getter(monkeypatch, nonce):
    contract = SimpleNamespace(nonce=0, _view_methods_={"nonce": lambda: nonce})
    safe = SimpleNamespace(address="0xabc", nonce=0, contract=contract)
    monkeypatch.setattr("ape.Contract", lambda address: contract)

    assert runtime.safe_onchain_nonce(safe) == nonce


def test_safe_onchain_nonce_fails_closed_when_getter_missing():
    safe = SimpleNamespace(nonce=0, contract=SimpleNamespace(_view_methods_={}))

    with pytest.raises(RuntimeError, match="could not read the Safe on-chain nonce"):
        runtime.safe_onchain_nonce(safe)


def test_safe_onchain_nonce_fails_closed_when_rpc_fails():
    error = TimeoutError("RPC timed out")

    def getter():
        raise error

    safe = SimpleNamespace(nonce=0, contract=SimpleNamespace(_view_methods_={"nonce": getter}))

    with pytest.raises(RuntimeError, match="RPC timed out") as raised:
        runtime.safe_onchain_nonce(safe)
    assert raised.value.__cause__ is error


class _ChainMgr:
    chain_id = 747474


class _SafeServiceDown:
    """Fake SafeAccount whose Tx Service nonce read fails."""

    chain_manager = _ChainMgr()

    def get_client(self, chain_id=None, override_url=None):
        return object()

    @property
    def new_nonce(self):
        raise RuntimeError("service unreachable")


def test_proposal_nonce_fails_closed_when_service_unreachable():
    # Must NOT fall back to the on-chain nonce: guessing it while queued txs exist would
    # propose a conflicting nonce. Fail closed so `send` aborts (PR review P2).
    ep = TxServiceEndpoint(
        base_url="https://safe-transaction-katana.safe.global/api",
        timeout=10,
        is_override=True,
    )
    with pytest.raises(RuntimeError, match="conflicting nonce"):
        runtime.proposal_nonce(_SafeServiceDown(), ep)


class _FakeResponse:
    ok = True


class _RecordingSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((url, kwargs.get("headers", {})))
        return _FakeResponse()


class _SafeWithRealClient:
    """Fake SafeAccount whose get_client builds a real ape-safe SafeClient."""

    chain_manager = _ChainMgr()
    address = "0x0000000000000000000000000000000000000001"

    def __init__(self):
        self.override_urls = []

    def get_client(self, chain_id=None, override_url=None):
        from ape_safe.client import SafeClient

        self.override_urls.append(override_url)
        client = SafeClient(address=self.address, chain_id=chain_id, override_url=override_url)
        client.__dict__["session"] = _RecordingSession()
        return client


@pytest.mark.parametrize(
    ("base_url", "sends_key"),
    [
        ("https://api.safe.global/tx-service/robinhood/api", True),
        ("https://multisig-txs.risechain.com/api", False),
        ("https://hostkey.svc.example/api", False),
    ],
)
def test_gateway_key_only_sent_to_safe_gateway(base_url, sends_key):
    ep = TxServiceEndpoint(base_url=base_url, timeout=10, is_override=not sends_key)
    safe = _SafeWithRealClient()
    runtime._inject_tx_service_client(safe, ep)

    # Always the resolved URL, so ape-safe never re-derives a gateway URL of its own.
    assert safe.override_urls == [base_url]
    client = safe.__dict__["client"]
    client._get("/safes/0x1")
    ((url, headers),) = client.session.calls
    assert url.startswith(base_url)
    assert ("Authorization" in headers) is sends_key
