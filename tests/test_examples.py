"""Task 10: the reference examples load and register against the real loader."""

from __future__ import annotations

from pathlib import Path

from safe_propose.loader import load_definitions, resolve

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_example_safe_txs_registers_katana_caps():
    names = load_definitions(EXAMPLES / "scripts" / "safe_txs.py")
    assert "katana_caps" in names
    assert resolve("katana_caps").__name__ == "katana_caps"


def test_example_ape_config_declares_supported_custom_networks():
    import yaml

    cfg = yaml.safe_load((EXAMPLES / "ape-config.yaml").read_text())
    custom = {c["ecosystem"]: c for c in cfg["networks"]["custom"]}
    assert custom["katana"]["chain_id"] == 747474
    assert custom["rise"]["chain_id"] == 4153
    assert custom["robinhood"]["chain_id"] == 4663
    assert "rise" in cfg["node"]
    assert "rise" in cfg["foundry"]["fork"]
    assert cfg["node"]["robinhood"]["mainnet"]["uri"] == "${ROBINHOOD_RPC}"
    assert "robinhood" in cfg["foundry"]["fork"]


def test_example_workflow_wires_every_builtin_network():
    import yaml

    from safe_propose.config import NETWORK_SPECS

    wf = yaml.safe_load((EXAMPLES / ".github" / "workflows" / "safe-propose.yml").read_text())
    job = wf["jobs"]["safe-propose"]
    run_envs = [s["env"] for s in job["steps"] if s.get("name", "").startswith(("Dry-run", "Send"))]
    assert len(run_envs) == 2
    for spec in NETWORK_SPECS.values():
        assert f"{spec.env_prefix}_SAFE_ADDRESS" in job["env"]
        for env in run_envs:
            assert f"{spec.env_prefix}_RPC" in env
