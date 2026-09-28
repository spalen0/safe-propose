"""Unit tests for txservice.py (TEST_PLAN Layer 1).

The non-negotiable invariant: every resolved endpoint carries a timeout, and selecting
the gateway without a key is a hard error (never a silent untimed attempt).
"""

from __future__ import annotations

import pytest

from safe_propose.txservice import OVERRIDE_URLS, TxServiceError, resolve_endpoint


def test_gateway_url_from_slug():
    ep = resolve_endpoint(1, gateway_api_key="key")
    assert ep.base_url == "https://api.safe.global/tx-service/eth/api"
    assert ep.is_override is False
    assert "key" not in repr(ep)


def test_optimism_uses_gateway():
    ep = resolve_endpoint(10, gateway_api_key="key")
    assert ep.is_override is False
    assert ep.base_url == "https://api.safe.global/tx-service/oeth/api"


def test_off_gateway_chain_without_service_errors():
    # Unknown chain → must error, never build a gateway URL that 404s.
    with pytest.raises(TxServiceError) as exc:
        resolve_endpoint(324, gateway_api_key="key")
    assert "no Safe Tx Service known for chain 324" in str(exc.value)


def test_off_gateway_chain_with_override_url():
    ep = resolve_endpoint(324, gateway_api_key="key", override_url="https://svc.example/api")
    assert ep.is_override is True
    assert ep.base_url == "https://svc.example/api"


def test_hyperevm_uses_gateway_slug():
    # Gateway slug is `hyper`, not the EIP-3770 shortname `hyper-evm`.
    ep = resolve_endpoint(999, gateway_api_key="present")
    assert ep.is_override is False
    assert ep.base_url == "https://api.safe.global/tx-service/hyper/api"


def test_katana_falls_back_to_keyless_override_without_key():
    ep = resolve_endpoint(747474, gateway_api_key=None)
    assert ep.is_override is True
    assert ep.base_url == OVERRIDE_URLS[747474]


def test_katana_uses_override_even_with_gateway_key():
    # The gateway/ape-safe client can't serve 747474, so a gateway key must not divert
    # Katana away from the standalone override (PR review P1).
    ep = resolve_endpoint(747474, gateway_api_key="present")
    assert ep.is_override is True
    assert ep.base_url == OVERRIDE_URLS[747474]


def test_rise_falls_back_to_keyless_override():
    ep = resolve_endpoint(4153, gateway_api_key=None)
    assert ep.is_override is True
    assert ep.base_url == "https://multisig-txs.risechain.com/api"


def test_robinhood_uses_gateway_slug():
    ep = resolve_endpoint(4663, gateway_api_key="present")
    assert ep.is_override is False
    assert ep.base_url == "https://api.safe.global/tx-service/robinhood/api"
    assert ep.timeout == 10.0


@pytest.mark.parametrize("chain_id", [999, 4663])
def test_slugged_gateway_chains_require_key(chain_id):
    # Safe rate-limits keyless gateway traffic; a 429 on the nonce read aborts `send`
    # mid-run, so fail up front like every other gateway chain.
    with pytest.raises(TxServiceError, match="APE_SAFE_GATEWAY_API_KEY"):
        resolve_endpoint(chain_id, gateway_api_key=None)


def test_builtin_overrides_are_off_the_gateway():
    # Anything on api.safe.global belongs in GATEWAY_SLUGS so it gets the key check.
    for url in OVERRIDE_URLS.values():
        ep = resolve_endpoint(1, gateway_api_key=None, override_url=url)
        assert ep.is_safe_gateway is False


def test_is_safe_gateway_only_for_safe_host():
    assert resolve_endpoint(1, gateway_api_key="key").is_safe_gateway is True
    explicit = "https://api.safe.global/tx-service/hyper/api"
    assert resolve_endpoint(1, gateway_api_key=None, override_url=explicit).is_safe_gateway
    for url in (
        "https://multisig-txs.risechain.com/api",
        "https://api.safe.global.evil.example/api",
        "http://api.safe.global/tx-service/eth/api",
        "https://svc.example/api?h=api.safe.global",
    ):
        ep = resolve_endpoint(1, gateway_api_key=None, override_url=url)
        assert ep.is_safe_gateway is False, url


def test_explicit_override_wins():
    ep = resolve_endpoint(1, gateway_api_key="key", override_url="https://my.service")
    assert ep.is_override is True
    assert ep.base_url == "https://my.service"


def test_gateway_without_key_raises():
    with pytest.raises(TxServiceError) as exc:
        resolve_endpoint(1, gateway_api_key=None)
    assert "APE_SAFE_GATEWAY_API_KEY" in str(exc.value)


def test_timeout_present_and_overridable():
    assert resolve_endpoint(1, gateway_api_key="key").timeout == 10.0
    assert resolve_endpoint(1, gateway_api_key="key", timeout=3).timeout == 3


def test_nonpositive_timeout_rejected():
    with pytest.raises(TxServiceError):
        resolve_endpoint(1, gateway_api_key="key", timeout=0)


def test_endpoint_repr_redacts_base_url():
    ep = resolve_endpoint(1, gateway_api_key="supersecret")
    text = repr(ep)
    assert "supersecret" not in text
    assert "***set***" in text
    assert "api_key" not in text


def test_endpoint_repr_redacts_override_url():
    url = "https://hostkey.svc.example/apikey-in-path?key=querysecret"
    ep = resolve_endpoint(1, gateway_api_key=None, override_url=url)
    text = repr(ep)
    assert "hostkey" not in text
    assert "apikey-in-path" not in text
    assert "querysecret" not in text
    assert "base_url='***set***'" in text


def test_endpoint_public_origin_is_scheme_and_host():
    ep = resolve_endpoint(747474, gateway_api_key=None)
    assert ep.public_origin() == "https://safe-transaction-katana.safe.global"


def test_endpoint_public_origin_shows_override_host(monkeypatch):
    monkeypatch.setenv("KATANA_TX_SERVICE_URL", "https://hostkey.svc.example/api?key=querysecret")
    ep = resolve_endpoint(
        1,
        gateway_api_key=None,
        override_url="https://hostkey.svc.example/api?key=querysecret",
    )
    shown = ep.public_origin()
    assert shown == "https://hostkey.svc.example"
    assert "querysecret" not in shown
    assert "/api" not in shown
