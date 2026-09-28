"""Deploy a throwaway **test Safe on live Katana** for end-to-end `send` validation.

Stands up a Safe owned by the proposer/delegate key so that `safe-propose send` can be
exercised against the *real* Safe Transaction Service with **zero production impact** (it
is your own safe, not the SAM Curator multisig). Spends a little real Katana gas from the
proposer key.

By default it deploys a **1-of-1 Safe owned by the proposer** (``PROPOSER_PRIVATE_KEY``),
so that account is both the owner and the proposer — no separate delegate registration is
needed for `propose_safe_tx`.

Usage::

    export KATANA_RPC=...          # or KATANA_RPC_2
    export PROPOSER_PRIVATE_KEY=...    # funds the deploy + owns the safe
    python scripts/deploy_test_safe.py

Prints the deployed safe address. Point the engine at it for a live send:

    export KATANA_SAFE_ADDRESS=<printed address>
    safe-propose send --fn <trivial_fn> --network katana

This is a deliberate, gas-spending, on-chain action — run it yourself when ready.
"""

from __future__ import annotations

import os
import signal
import sys
import tempfile
from pathlib import Path

OWNERS_ENV = "TEST_SAFE_OWNERS"  # optional comma-separated; default: the proposer address
THRESHOLD_ENV = "TEST_SAFE_THRESHOLD"  # optional; default 1


def main() -> int:
    rpc = os.environ.get("KATANA_RPC_2") or os.environ.get("KATANA_RPC")
    if not (rpc and os.environ.get("PROPOSER_PRIVATE_KEY")):
        print("SKIP: set a Katana RPC and PROPOSER_PRIVATE_KEY")
        return 2

    signal.alarm(180)

    tmp = Path(tempfile.mkdtemp(prefix="sp-deploy-safe-"))
    (tmp / "ape-config.yaml").write_text(
        "name: sp-deploy-safe\n"
        "networks:\n  custom:\n    - name: mainnet\n      ecosystem: katana\n"
        "      chain_id: 747474\n      base_ecosystem_plugin: ethereum\n"
        f"node:\n  katana:\n    mainnet:\n      uri: {rpc}\n"
    )
    os.environ["APE_DATA_FOLDER"] = str(tmp / ".ape")
    os.chdir(tmp)

    from ape import networks
    from ape_safe.factory import SafeFactory

    from safe_propose.runtime import import_key_account

    threshold = int(os.environ.get(THRESHOLD_ENV, "1"))

    # NB: we do NOT resolve_config() here — that requires KATANA_SAFE_ADDRESS, but this
    # script's whole job is to deploy a Safe that doesn't exist yet. We only need the RPC
    # (in ape-config above) and the proposer key.
    with networks.parse_network_choice("katana:mainnet:node"):
        proposer = import_key_account("sp-deploy-proposer", os.environ["PROPOSER_PRIVATE_KEY"])
        owners_raw = os.environ.get(OWNERS_ENV, "")
        owners = [o.strip() for o in owners_raw.split(",") if o.strip()] or [proposer.address]
        print(f"deploying Safe owners={owners} threshold={threshold} from {proposer.address}")

        # On live Katana the canonical Safe singleton/factory already exist, so we use
        # SafeFactory().create directly (no inject, which is only for fresh local chains).
        safe = SafeFactory().create(
            owners=owners, threshold=threshold, version="1.4.1", sender=proposer
        )
        print(f"DEPLOYED test Safe: {safe.address}")
        print("Next: export KATANA_SAFE_ADDRESS=" + safe.address)
        print("      safe-propose send --fn <trivial_fn> --network katana")
    return 0


if __name__ == "__main__":
    sys.exit(main())
