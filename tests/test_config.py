"""Unit tests for config.py precedence + errors (TEST_PLAN Layer 1)."""

from __future__ import annotations

import pytest

from safe_propose.config import ConfigError, normalize_network, resolve_config

# Resolve against no ape-config file so only CLI/env/defaults are in play.
NO_APE = "/nonexistent/ape-config.yaml"


def test_alias_normalization():
    assert normalize_network("eth") == "ethereum"
    assert normalize_network("ARB") == "arbitrum"
    assert normalize_network("katana") == "katana"
    assert normalize_network("RobinhoodChain") == "robinhood"


def test_env_resolves_safe_and_rpc():
    env = {
        "KATANA_SAFE_ADDRESS": "0x90D0f26025571295D18a6c041E47450B81886B51",
        "KATANA_RPC": "https://rpc.example/katana",
    }
    cfg = resolve_config("katana", env=env, ape_config_path=NO_APE)
    assert cfg.chain_id == 747474
    assert cfg.safe_address.endswith("6B51")
    assert cfg.rpc_uri == "https://rpc.example/katana"
    assert cfg.safe_shortname == "katana"


def test_cli_overrides_env():
    env = {
        "KATANA_SAFE_ADDRESS": "0xaaa",
        "KATANA_RPC": "https://env",
    }
    cfg = resolve_config(
        "katana",
        cli={"safe_address": "0xbbb", "rpc_uri": "https://cli"},
        env=env,
        ape_config_path=NO_APE,
    )
    assert cfg.safe_address == "0xbbb"
    assert cfg.rpc_uri == "https://cli"


def test_missing_safe_address_errors():
    with pytest.raises(ConfigError) as exc:
        resolve_config("katana", env={"KATANA_RPC": "x"}, ape_config_path=NO_APE)
    assert "KATANA_SAFE_ADDRESS" in str(exc.value)


def test_safe_address_falls_back_to_eth_mainnet():
    # A per-chain address overrides; otherwise ETH_SAFE_ADDRESS covers every chain.
    cfg = resolve_config(
        "katana",
        env={"ETH_SAFE_ADDRESS": "0xeee", "KATANA_RPC": "x"},
        ape_config_path=NO_APE,
    )
    assert cfg.safe_address == "0xeee"
    assert cfg.safe_address_fallback is True

    cfg = resolve_config(
        "katana",
        env={"ETH_SAFE_ADDRESS": "0xeee", "KATANA_SAFE_ADDRESS": "0xkkk", "KATANA_RPC": "x"},
        ape_config_path=NO_APE,
    )
    assert cfg.safe_address == "0xkkk"  # per-chain wins over the fallback
    assert cfg.safe_address_fallback is False

    cfg = resolve_config(
        "katana",
        cli={"safe_address": "0xccc"},
        env={"ETH_SAFE_ADDRESS": "0xeee", "KATANA_RPC": "x"},
        ape_config_path=NO_APE,
    )
    assert cfg.safe_address == "0xccc"  # --safe-address is explicit, not a fallback
    assert cfg.safe_address_fallback is False

    cfg = resolve_config(
        "ethereum", env={"ETH_SAFE_ADDRESS": "0xeee", "ETH_RPC": "x"}, ape_config_path=NO_APE
    )
    assert cfg.safe_address_fallback is False  # ethereum's own address


def test_missing_rpc_for_custom_network_errors():
    with pytest.raises(ConfigError) as exc:
        resolve_config("katana", env={"KATANA_SAFE_ADDRESS": "0x1"}, ape_config_path=NO_APE)
    assert "KATANA_RPC" in str(exc.value)


def test_every_network_requires_rpc():
    # All networks connect via the node provider, so an explicit RPC is required.
    with pytest.raises(ConfigError) as exc:
        resolve_config("ethereum", env={"ETH_SAFE_ADDRESS": "0x1"}, ape_config_path=NO_APE)
    assert "ETH_RPC" in str(exc.value)


def test_supported_networks_resolve():
    # chain id, env prefix, and EIP-3770 shortname per network (incl. the new ones).
    expected = {
        "ethereum": (1, "ETH", "eth"),
        "base": (8453, "BASE", "base"),
        "arbitrum": (42161, "ARB", "arb1"),
        "optimism": (10, "OP", "oeth"),
        "hyperevm": (999, "HYPEREVM", "hyper-evm"),
        "katana": (747474, "KATANA", "katana"),
        "rise": (4153, "RISE", "rise"),
        "robinhood": (4663, "ROBINHOOD", "robinhood"),
    }
    for net, (chain_id, prefix, shortname) in expected.items():
        env = {f"{prefix}_SAFE_ADDRESS": "0x1", f"{prefix}_RPC": "https://rpc"}
        cfg = resolve_config(net, env=env, ape_config_path=NO_APE)
        assert (cfg.chain_id, cfg.env_prefix, cfg.safe_shortname) == (chain_id, prefix, shortname)


def test_aliases_resolve():
    assert normalize_network("op") == "optimism"
    assert normalize_network("hyper") == "hyperevm"


def test_robinhood_queue_link_uses_safe_prefix():
    cfg = resolve_config(
        "robinhood",
        env={"ROBINHOOD_SAFE_ADDRESS": "0x1234", "ROBINHOOD_RPC": "https://rpc.example"},
        ape_config_path=NO_APE,
    )
    assert cfg.queue_url == "https://app.safe.global/transactions/queue?safe=robinhood:0x1234"


def test_tx_service_url_override():
    env = {
        "HYPEREVM_SAFE_ADDRESS": "0x1",
        "HYPEREVM_RPC": "x",
        "HYPEREVM_TX_SERVICE_URL": "https://svc/api",
    }
    cfg = resolve_config("hyperevm", env=env, ape_config_path=NO_APE)
    assert cfg.tx_service_url == "https://svc/api"


def test_safe_queue_url_override():
    env = {
        "RISE_SAFE_ADDRESS": "0x60C6E21be8B2f7118823FbEB15B1be22EAe1de11",
        "RISE_RPC": "https://rpc.risechain.com",
        "RISE_SAFE_QUEUE_URL": "https://multisig.risechain.com/home",
    }
    cfg = resolve_config("rise", env=env, ape_config_path=NO_APE)
    assert cfg.queue_url == (
        "https://multisig.risechain.com/home?safe=rise:0x60C6E21be8B2f7118823FbEB15B1be22EAe1de11"
    )


def test_unknown_network_errors():
    with pytest.raises(ConfigError) as exc:
        resolve_config("dogechain", env={}, ape_config_path=NO_APE)
    assert "unknown network" in str(exc.value)


def test_custom_network_from_ape_config(tmp_path):
    ape = tmp_path / "ape-config.yaml"
    ape.write_text(
        "networks:\n"
        "  custom:\n"
        "    - name: mainnet\n"
        "      ecosystem: zkfoo\n"
        "      chain_id: 999999\n"
    )
    env = {"ZKFOO_SAFE_ADDRESS": "0x1", "ZKFOO_RPC": "https://z"}
    cfg = resolve_config("zkfoo", env=env, ape_config_path=str(ape))
    assert cfg.chain_id == 999999


def test_repr_redacts_secrets():
    env = {
        "ETH_SAFE_ADDRESS": "0x1",
        "ETH_RPC": "https://user:pass@rpchostkey.rpc.example/v2/supersecretkey",
        "ETHERSCAN_TOKEN": "scansecret",
        "PROPOSER_PRIVATE_KEY": "0xdeadbeef",
        "APE_SAFE_GATEWAY_API_KEY": "gwsecret",
        "ETH_TX_SERVICE_URL": "https://svchostkey.svc.example/api?key=svcquerykey",
    }
    cfg = resolve_config("ethereum", env=env, ape_config_path=NO_APE)
    text = repr(cfg)
    assert "0xdeadbeef" not in text
    assert "gwsecret" not in text
    assert "scansecret" not in text
    assert "supersecretkey" not in text
    assert "user:pass" not in text
    assert "rpchostkey" not in text
    assert "svchostkey" not in text
    assert "svcquerykey" not in text
    assert "***set***" in text
    assert "rpc_uri='***set***'" in text
    assert "tx_service_url='***set***'" in text


def test_redact_error_text_strips_credential_urls():
    from safe_propose.config import redact_error_text

    secret = "https://user:pass@rpchostkey.rpc.example/v2/supersecretkey"
    text = redact_error_text(f"401 Client Error for url: {secret}", env={})
    assert secret not in text
    assert "supersecretkey" not in text
    assert "rpchostkey" not in text
    assert "user:pass" not in text
    assert "***url***" in text
    assert redact_error_text("RPC timeout", env={}) == "RPC timeout"
    assert "***url***" in redact_error_text("wss://hostkey.example/ws?token=abc", env={})


def test_redact_error_text_uses_configured_rpc_fragments():
    from safe_propose.config import redact_error_text

    rpc = "https://abc.quiknode.pro/supersecretkey/"
    msg = (
        "HTTPSConnectionPool(host='abc.quiknode.pro', port=443): "
        "Max retries exceeded with url: /supersecretkey/"
    )
    text = redact_error_text(msg, env={"KATANA_RPC": rpc})
    assert "supersecretkey" not in text
    assert "abc.quiknode.pro" not in text
    assert "***" in text


def test_redact_error_text_does_not_replace_rpc_host_labels():
    from safe_propose.config import redact_error_text

    rpc = "https://hyperliquid.llamarpc.com/supersecretkey/"
    msg = (
        "hyperliquid oracle stale; llamarpc_quote(); "
        "HTTPSConnectionPool(host='hyperliquid.llamarpc.com', port=443): "
        "Max retries exceeded with url: /supersecretkey/"
    )
    text = redact_error_text(msg, env={"HYPEREVM_RPC": rpc})
    assert "supersecretkey" not in text
    assert "hyperliquid.llamarpc.com" not in text
    assert "hyperliquid oracle stale" in text
    assert "llamarpc_quote()" in text


def test_redact_error_text_keeps_tx_service_host():
    from safe_propose.config import redact_error_text

    env = {"SAFE_TX_SERVICE_URL": "https://safe-transaction-katana.safe.global/api?key=svcquerykey"}
    text = redact_error_text(
        "leftover tx-service host='safe-transaction-katana.safe.global' key=svcquerykey",
        env=env,
    )
    assert "safe-transaction-katana.safe.global" in text
    assert "svcquerykey" not in text


def test_timeout_default_and_override():
    env = {"KATANA_SAFE_ADDRESS": "0x1", "KATANA_RPC": "x"}
    assert resolve_config("katana", env=env, ape_config_path=NO_APE).request_timeout == 10.0
    env2 = {**env, "SAFE_TRANSACTION_SERVICE_REQUEST_TIMEOUT": "5"}
    assert resolve_config("katana", env=env2, ape_config_path=NO_APE).request_timeout == 5.0
