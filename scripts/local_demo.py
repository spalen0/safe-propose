"""Local MVP demo: build → sign → execute a Safe tx on a local fork, no Tx Service.

The minimal end-to-end you can run yourself to prove the pipeline lands a transaction on
a Safe multisig — *locally*, with no external Safe Transaction Service and no fancy
features:

  1. fork the configured chain with foundry/anvil (local node),
  2. deploy a fresh **1-of-1 Safe we own** (owner = an anvil test account),
  3. build a tx through the engine (a token ``approve``, inline ABI — no explorer needed)
     and assert our offline ``safe_tx_hash`` equals the Safe's on-chain
     ``getTransactionHash`` (the build-correctness / redundancy guarantee),
  4. sign as the owner and **execute it on-chain**,
  5. read the resulting state back to prove it landed.

Because we own the Safe, signatures are real (no impersonation / ``GS025``), and because
we execute directly there is no Tx Service dependency.

Usage::

    export KATANA_RPC=...   # or KATANA_RPC_2 (an Alchemy/Tenderly Katana RPC)
    python scripts/local_demo.py

Prints ``DEMO: OK`` on success. Requires the dev extras (eth-ape, ape-safe, ape-foundry)
and the ``anvil`` binary (foundry).
"""

from __future__ import annotations

import json
import os
import signal
import sys
import tempfile
from pathlib import Path

# A real ERC20 on Katana (the og-usdc vault token) — used only as a call target so the
# demo needs no compiler and no explorer. approve() always succeeds regardless of balance.
TOKEN = "0xCE2b8e464Fc7b5E58710C24b7e5EBFB6027f29D7"
SPENDER = "0x000000000000000000000000000000000000dEaD"
AMOUNT = 12345
ERC20 = [
    {
        "name": "approve",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "s", "type": "address"}, {"name": "a", "type": "uint256"}],
        "outputs": [{"type": "bool"}],
    },
    {
        "name": "allowance",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "o", "type": "address"}, {"name": "s", "type": "address"}],
        "outputs": [{"type": "uint256"}],
    },
]


def main() -> int:
    rpc = os.environ.get("KATANA_RPC_2") or os.environ.get("KATANA_RPC")
    if not rpc:
        print("SKIP: set KATANA_RPC (or KATANA_RPC_2) to a Katana RPC")
        return 2

    signal.alarm(180)  # never hang

    tmp = Path(tempfile.mkdtemp(prefix="sp-local-demo-"))
    (tmp / "ape-config.yaml").write_text(
        "name: sp-local-demo\n"
        "networks:\n  custom:\n    - name: mainnet\n      ecosystem: katana\n"
        "      chain_id: 747474\n      base_ecosystem_plugin: ethereum\n"
        f"node:\n  katana:\n    mainnet:\n      uri: {rpc}\n"
        "foundry:\n  fork:\n    katana:\n      mainnet:\n        upstream_provider: node\n"
    )
    os.environ["APE_DATA_FOLDER"] = str(tmp / ".ape")
    os.chdir(tmp)

    from ape import Contract, accounts, networks
    from ape_safe.factory import SafeFactory
    from packaging.version import Version

    from safe_propose import engine
    from safe_propose.context import Ctx, make_const

    def approve_tx(batch, ctx):
        """A tx definition, exactly as a consuming repo would write it."""
        batch.add(ctx.contract(TOKEN, abi=ERC20).approve, SPENDER, AMOUNT)

    with networks.parse_network_choice("katana:mainnet-fork:foundry"):
        owner = accounts.test_accounts[0]
        print(f"[1/5] forked Katana locally; owner={owner.address}")

        SafeFactory.inject(Version("1.4.1"), owner)
        safe_contract = SafeFactory().create(
            owners=[owner.address], threshold=1, version="1.4.1", sender=owner
        )
        print(f"[2/5] deployed 1-of-1 Safe at {safe_contract.address}")

        safe_dir = Path(os.environ["APE_DATA_FOLDER"]) / "safe"
        safe_dir.mkdir(parents=True, exist_ok=True)
        (safe_dir / "demo.json").write_text(
            json.dumps({"address": safe_contract.address, "deployed_chain_ids": [747474]})
        )
        safe = accounts.load("demo")

        ctx = Ctx(
            network="katana",
            chain_id=747474,
            safe_address=safe.address,
            const=make_const({}),
            _contract=lambda a, abi=None: Contract(a, abi=abi),
        )
        batch = engine.build(approve_tx, ctx, safe)
        safe_tx, safe_tx_hash, nonce = engine.build_safe_tx(batch, safe, nonce=0)
        # Correctness check: our offline hash must equal the Safe's own getTransactionHash.
        onchain_hash = "0x" + bytes(safe_contract.getTransactionHash(*safe_tx)).hex()
        if safe_tx_hash.lower() != onchain_hash.lower():
            print(f"DEMO: HASH MISMATCH offline={safe_tx_hash} onchain={onchain_hash}")
            return 1
        print(f"[3/5] built safe_tx_hash={safe_tx_hash} nonce={nonce} (matches on-chain)")

        receipt = engine.execute_safe_tx(safe, safe_tx, signers=[owner])
        print(f"[4/5] executed on-chain (gas={receipt.gas_used})")

        allowance = Contract(TOKEN, abi=ERC20).allowance(safe.address, SPENDER)
        print(f"[5/5] on-chain allowance(safe→spender) = {allowance} (expected {AMOUNT})")
        if allowance != AMOUNT:
            print("DEMO: MISMATCH")
            return 1
    print("DEMO: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
